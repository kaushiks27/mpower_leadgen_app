"""Auth router — /api/auth/{login,logout,me,me/name,forgot-password,
reset-password,change-password}. Email+password login issues a sha256-hashed
user-bound session row; the plaintext token goes into the `mp_session` cookie.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    OkResponse,
    ResetPasswordRequest,
    UserNameUpdate,
)
from app.auth.orm import PasswordResetToken, User
from app.auth.passwords import (
    DUMMY_HASH,
    MIN_PASSWORD_LEN,
    hash_password,
    verify_password,
)
from app.auth.sessions import (
    SESSION_COOKIE,
    SESSION_TTL,
    create_session,
    get_session_and_user,
    revoke_session,
)
from app.email import EmailDeliveryError, send_email
from app.email.templates import build_reset_email
from app.db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESET_TOKEN_TTL = timedelta(hours=1)


def _normalize_email(raw: str | None) -> str:
    return (raw or "").strip().lower()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cookie_kwargs() -> dict[str, object]:
    is_prod = os.environ.get("ENV", "dev").lower() == "prod"
    return {
        "key": SESSION_COOKIE,
        "httponly": True,
        "samesite": "lax",
        "secure": is_prod,
        "max_age": int(SESSION_TTL.total_seconds()),
        "path": "/",
    }


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> LoginResponse:
    email = _normalize_email(payload.email)
    if not EMAIL_REGEX.match(email):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="wrong email or password"
        )
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    hash_to_check = user.password_hash if user is not None else DUMMY_HASH
    valid = verify_password(payload.password, hash_to_check)
    if user is None or not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="wrong email or password"
        )
    raw_token, _ = await create_session(db, user)
    response.set_cookie(value=raw_token, **_cookie_kwargs())
    return LoginResponse(ok=True)


@router.post("/logout", response_model=LoginResponse)
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_session),
    mp_session: str | None = Cookie(default=None),
) -> LoginResponse:
    await revoke_session(db, mp_session)
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return LoginResponse(ok=True)


@router.get("/me", response_model=MeResponse)
async def me(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> MeResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        result = await get_session_and_user(db, token)
        if result is not None:
            _, user = result
            return MeResponse(
                signed_in=True,
                id=user.id,
                email=user.email,
                role=user.role,
                first_name=user.first_name,
                last_name=user.last_name,
            )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="not signed in"
    )


@router.patch("/me/name", response_model=MeResponse)
async def update_my_name(
    body: UserNameUpdate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> MeResponse:
    first = body.first_name.strip()
    last = body.last_name.strip()
    if not first or not last:
        raise HTTPException(status_code=400, detail="first/last name required")
    current.first_name = first
    current.last_name = last
    await db.commit()
    await db.refresh(current)
    return MeResponse(
        signed_in=True,
        id=current.id,
        email=current.email,
        role=current.role,
        first_name=current.first_name,
        last_name=current.last_name,
    )


@router.post("/forgot-password", response_model=OkResponse)
async def forgot_password(
    req: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_session),
) -> OkResponse:
    """Always 200 — no enumeration. Reset URL also logged for ops/dev."""
    email = _normalize_email(req.email)
    if not EMAIL_REGEX.match(email):
        return OkResponse()
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        return OkResponse()
    raw = secrets.token_urlsafe(32)
    now = _now_utc()
    db.add(
        PasswordResetToken(
            token_hash=_hash_token(raw),
            user_id=user.id,
            created_at=now,
            expires_at=now + RESET_TOKEN_TTL,
        )
    )
    await db.commit()
    base_url = os.environ.get("APP_BASE_URL", "http://localhost:3030").rstrip("/")
    link = f"{base_url}/reset-password?token={raw}"
    logger.info("[forgot-password] reset link for %s: %s", email, link)
    subject, html, text = build_reset_email(reset_url=link, recipient_email=email)
    try:
        send_email(to=email, subject=subject, html=html, text=text)
    except EmailDeliveryError as e:
        logger.warning("[forgot-password] email send failed for %s: %s", email, e)
    return OkResponse()


@router.post("/reset-password", response_model=OkResponse)
async def reset_password(
    req: ResetPasswordRequest,
    db: AsyncSession = Depends(get_session),
) -> OkResponse:
    if len(req.new_password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400, detail="password must be at least 8 characters"
        )
    h = _hash_token(req.token)
    row = (
        await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == h)
        )
    ).scalar_one_or_none()
    if row is None or row.consumed_at is not None or row.expires_at <= _now_utc():
        raise HTTPException(
            status_code=400, detail="this link has expired or is invalid"
        )
    user = await db.get(User, row.user_id)
    if user is None:
        raise HTTPException(
            status_code=400, detail="this link has expired or is invalid"
        )
    user.password_hash = hash_password(req.new_password)
    row.consumed_at = _now_utc()
    await db.commit()
    return OkResponse()


@router.post("/change-password", response_model=OkResponse)
async def change_password(
    req: ChangePasswordRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> OkResponse:
    if not verify_password(req.current_password, current.password_hash):
        raise HTTPException(status_code=400, detail="current password is incorrect")
    if len(req.new_password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400, detail="password must be at least 8 characters"
        )
    if req.new_password == req.current_password:
        raise HTTPException(
            status_code=400, detail="new password must differ from current"
        )
    current.password_hash = hash_password(req.new_password)
    await db.commit()
    return OkResponse()
