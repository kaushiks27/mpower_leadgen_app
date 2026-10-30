"""User-bound session helpers — login issues a random token, sha256(token) is
stored on the row, plaintext goes into the `mp_session` cookie. Sliding 7-day TTL.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.orm import User, UserSession

SESSION_COOKIE = "mp_session"
SESSION_TTL = timedelta(days=7)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def create_session(db: AsyncSession, user: User) -> tuple[str, UserSession]:
    raw = secrets.token_urlsafe(32)
    now = _now_utc()
    row = UserSession(
        token_hash=_hash_token(raw),
        user_id=user.id,
        created_at=now,
        expires_at=now + SESSION_TTL,
        last_seen_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return raw, row


async def revoke_session(db: AsyncSession, raw_token: str | None) -> None:
    if not raw_token:
        return
    h = _hash_token(raw_token)
    row = (
        await db.execute(select(UserSession).where(UserSession.token_hash == h))
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()


async def get_session_and_user(
    db: AsyncSession, raw_token: str | None
) -> tuple[UserSession, User] | None:
    if not raw_token:
        return None
    h = _hash_token(raw_token)
    row = (
        await db.execute(select(UserSession).where(UserSession.token_hash == h))
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at <= _now_utc():
        return None
    user = await db.get(User, row.user_id)
    if user is None:
        return None
    # Sliding TTL — touch last_seen_at + extend expiry on every authed hit.
    now = _now_utc()
    row.last_seen_at = now
    row.expires_at = now + SESSION_TTL
    await db.commit()
    return row, user
