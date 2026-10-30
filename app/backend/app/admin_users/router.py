"""Admin-only user management.

GET    /api/admin/users
POST   /api/admin/users/invite
POST   /api/admin/users/{id}/resend
DELETE /api/admin/users/{id}
PATCH  /api/admin/users/{id}/role
POST   /api/admin/users/activate    (public — token-gated)
"""

from __future__ import annotations

import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import activation
from app.auth.dependencies import get_current_user
from app.auth.models import (
    ActivatePayload,
    AdminUserRow,
    InviteUserPayload,
    OkResponse,
    RoleUpdatePayload,
)
from app.auth.orm import User
from app.auth.permissions import ALLOWED_ROLES, require_role
from app.email import EmailDeliveryError, send_email
from app.email.templates import build_invite_email, build_invite_reminder_email
from app.db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NAME_LEN = 80


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _activate_url(raw_token: str) -> str:
    base_url = os.environ.get("APP_BASE_URL", "http://localhost:3030").rstrip("/")
    return f"{base_url}/activate?token={raw_token}"


@router.get(
    "",
    response_model=list[AdminUserRow],
    dependencies=[Depends(require_role("admin"))],
)
async def list_users(db: AsyncSession = Depends(get_session)) -> list[AdminUserRow]:
    rows = (await db.execute(select(User).order_by(User.email))).scalars().all()
    return [
        AdminUserRow(
            id=u.id,
            email=u.email,
            first_name=u.first_name,
            last_name=u.last_name,
            role=u.role,
            pending=activation.is_pending(u),
            created_at=u.created_at.isoformat() if u.created_at else "",
        )
        for u in rows
    ]


def _send_invite_or_softfail(*, to: str, activate_url: str, builder) -> OkResponse:
    subject, html, text = builder(activate_url=activate_url, invitee_email=to)
    logger.info("[invite] activation link for %s: %s", to, activate_url)
    try:
        send_email(to=to, subject=subject, html=html, text=text)
    except EmailDeliveryError as e:
        logger.warning("[invite] email send failed for %s: %s", to, e)
        return OkResponse(
            email_failed=True,
            fallback_url=activate_url,
            fallback_message=(
                "email delivery failed — copy the activation link below and "
                "share it manually."
            ),
        )
    return OkResponse()


@router.post(
    "/invite",
    response_model=OkResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def invite_user(
    payload: InviteUserPayload, db: AsyncSession = Depends(get_session)
) -> OkResponse:
    email = _normalize_email(payload.email)
    first = payload.first_name.strip()
    last = payload.last_name.strip()
    role = (payload.role or "").strip().lower()
    if not EMAIL_REGEX.match(email):
        raise HTTPException(status_code=400, detail="invalid email")
    if not first or len(first) > MAX_NAME_LEN:
        raise HTTPException(status_code=400, detail="first name required")
    if not last or len(last) > MAX_NAME_LEN:
        raise HTTPException(status_code=400, detail="last name required")
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="invalid role")

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if existing is not None and not activation.is_pending(existing):
        raise HTTPException(
            status_code=400,
            detail="user already exists; change their role from the table instead",
        )

    if existing is None:
        user = User(
            email=email,
            password_hash=activation.PENDING_PASSWORD_SENTINEL,
            role=role,
            first_name=first,
            last_name=last,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        existing.first_name = first
        existing.last_name = last
        existing.role = role
        user = existing
        await db.commit()
        await db.refresh(user)

    await activation.invalidate_open_tokens(db, user.id)
    raw_token, _ = await activation.issue_activation_token(db, user.id)
    return _send_invite_or_softfail(
        to=email, activate_url=_activate_url(raw_token), builder=build_invite_email
    )


@router.post(
    "/{user_id}/resend",
    response_model=OkResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def resend_invite(
    user_id: int, db: AsyncSession = Depends(get_session)
) -> OkResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if not activation.is_pending(user):
        raise HTTPException(
            status_code=400, detail="user has already activated; nothing to resend"
        )
    await activation.invalidate_open_tokens(db, user.id)
    raw_token, _ = await activation.issue_activation_token(db, user.id)
    return _send_invite_or_softfail(
        to=user.email,
        activate_url=_activate_url(raw_token),
        builder=build_invite_reminder_email,
    )


@router.delete(
    "/{user_id}",
    response_model=OkResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def delete_user(
    user_id: int,
    admin: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> OkResponse:
    if user_id == admin.id:
        raise HTTPException(
            status_code=400, detail="you cannot delete your own account"
        )
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    await activation.invalidate_open_tokens(db, user.id)
    await db.delete(user)
    await db.commit()
    return OkResponse()


@router.patch(
    "/{user_id}/role",
    response_model=OkResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def change_user_role(
    user_id: int,
    payload: RoleUpdatePayload,
    admin: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> OkResponse:
    role = (payload.role or "").strip().lower()
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="invalid role")
    if user_id == admin.id:
        raise HTTPException(
            status_code=400, detail="you cannot change your own role"
        )
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.role = role
    await db.commit()
    return OkResponse()


@router.post("/activate", response_model=OkResponse)
async def activate_account(
    payload: ActivatePayload, db: AsyncSession = Depends(get_session)
) -> OkResponse:
    """Public — token-gated. Consumes the activation token + sets the password."""
    user = await activation.consume_activation_token(
        db, payload.token, payload.new_password
    )
    if user is None:
        raise HTTPException(
            status_code=400, detail="this link has expired or is invalid"
        )
    return OkResponse()
