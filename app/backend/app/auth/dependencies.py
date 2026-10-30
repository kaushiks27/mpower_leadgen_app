"""FastAPI dependencies — gate routes behind a valid user-bound session."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.orm import User, UserSession
from app.auth.sessions import SESSION_COOKIE, get_session_and_user
from app.db import get_session

_NOT_SIGNED_IN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="not signed in"
)


async def require_session(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> None:
    """Pass iff a valid user-bound session cookie is present."""
    token = request.cookies.get(SESSION_COOKIE)
    if token and await get_session_and_user(db, token) is not None:
        return None
    raise _NOT_SIGNED_IN


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _NOT_SIGNED_IN
    result = await get_session_and_user(db, token)
    if result is None:
        raise _NOT_SIGNED_IN
    _, user = result
    return user


async def get_current_session(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> UserSession:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _NOT_SIGNED_IN
    result = await get_session_and_user(db, token)
    if result is None:
        raise _NOT_SIGNED_IN
    sess, _ = result
    return sess
