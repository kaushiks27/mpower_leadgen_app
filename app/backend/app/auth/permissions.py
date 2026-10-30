"""Role guard. `require_role(*allowed)` returns a FastAPI dep — 403 if the
authenticated user's role is not in `allowed`. 401 (from get_current_user)
takes precedence over 403.

mPower Lead-Gen v0 roles: `admin` | `rep`.
"""

from __future__ import annotations

from typing import Callable, Literal

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.orm import User

Role = Literal["admin", "rep"]

ALLOWED_ROLES = {"admin", "rep"}

FORBIDDEN_DETAIL = "you don't have permission to do this"


def require_role(*allowed: Role) -> Callable:
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN_DETAIL
            )
        return user

    return _dep
