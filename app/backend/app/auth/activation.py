"""Activation-token helpers (invite / first-admin bootstrap).

Lives in `auth/` (infra-grade) so both `auth.seed` and the `admin_users`
feature module can use it without crossing module boundaries the wrong way
(admin_users -> auth is allowed; auth -> admin_users is not).

Random 32-byte URL-safe token, sha256 stored on the row, plaintext returned to
the caller (caller emails it). Pending users have
`password_hash == PENDING_PASSWORD_SENTINEL`.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.orm import ActivationToken, User
from app.auth.passwords import hash_password

PENDING_PASSWORD_SENTINEL = "__pending_activation__"
ACTIVATION_TTL = timedelta(days=7)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_pending(user: User) -> bool:
    return user.password_hash == PENDING_PASSWORD_SENTINEL


async def issue_activation_token(
    db: AsyncSession, user_id: int
) -> tuple[str, ActivationToken]:
    raw = secrets.token_urlsafe(32)
    now = _now_utc()
    row = ActivationToken(
        token_hash=_hash_token(raw),
        user_id=user_id,
        created_at=now,
        expires_at=now + ACTIVATION_TTL,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return raw, row


async def consume_activation_token(
    db: AsyncSession, raw_token: str, new_password: str
) -> User | None:
    h = _hash_token(raw_token)
    row = (
        await db.execute(select(ActivationToken).where(ActivationToken.token_hash == h))
    ).scalar_one_or_none()
    if row is None or row.consumed_at is not None or row.expires_at <= _now_utc():
        return None
    user = await db.get(User, row.user_id)
    if user is None:
        return None
    user.password_hash = hash_password(new_password)
    row.consumed_at = _now_utc()
    await db.commit()
    return user


async def invalidate_open_tokens(db: AsyncSession, user_id: int) -> None:
    now = _now_utc()
    await db.execute(
        update(ActivationToken)
        .where(ActivationToken.user_id == user_id)
        .where(ActivationToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    await db.commit()
