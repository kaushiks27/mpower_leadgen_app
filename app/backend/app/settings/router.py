"""Admin-only API-key settings.

GET    /api/settings/keys              list provider key statuses (masked)
PUT    /api/settings/keys/{provider}   set / rotate a key (encrypted at rest)
DELETE /api/settings/keys/{provider}   clear DB key (reverts to env fallback)

Keys are write-only — no endpoint ever returns a plaintext key.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import require_role
from app.db import get_session
from app.settings import keys as keys_mod
from app.settings.models import KeyStatus, SetKeyPayload
from app.settings.orm import PROVIDERS

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_role("admin"))],
)


def _require_provider(provider: str) -> str:
    p = (provider or "").strip().lower()
    if p not in PROVIDERS:
        raise HTTPException(status_code=400, detail="unknown provider")
    return p


@router.get("/keys", response_model=list[KeyStatus])
async def list_keys() -> list[KeyStatus]:
    return [KeyStatus(**s) for s in keys_mod.all_statuses()]


@router.put("/keys/{provider}", response_model=KeyStatus)
async def set_key(
    provider: str,
    payload: SetKeyPayload,
    db: AsyncSession = Depends(get_session),
) -> KeyStatus:
    p = _require_provider(provider)
    raw = payload.api_key.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="api key required")
    await keys_mod.set_api_key(db, p, raw)
    return KeyStatus(**keys_mod.key_status(p))


@router.delete("/keys/{provider}", response_model=KeyStatus)
async def clear_key(
    provider: str, db: AsyncSession = Depends(get_session)
) -> KeyStatus:
    p = _require_provider(provider)
    await keys_mod.clear_api_key(db, p)
    return KeyStatus(**keys_mod.key_status(p))
