"""Admin credit-ceiling settings (admin-only).

GET  /api/enrichment/ceilings            per-provider monthly ceiling + usage
PUT  /api/enrichment/ceilings/{provider} set a provider's monthly ceiling

08062026_cr CR-2: the campaign-scoped enrich routes
(`POST /api/campaigns/{id}/enrich`, `GET …/enrich-status`) were REMOVED — the
campaign page no longer enriches; enrichment happens in the master Generate-Leads
wizard. The enrich service (`app.enrichment.service`) is retained (still
unit-tested + used by the wizard). The credit-ceiling settings below stay (Cost
+ Settings depend on them).

Admin-only. A full ceiling / missing key returns a clean 400 — never a raw 500.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import require_role
from app.db import get_session
from app.enrichment import credits
from app.enrichment.models import CeilingRow, CeilingUpdate
from app.enrichment.orm import METERED_PROVIDERS

router = APIRouter(
    prefix="/api",
    tags=["enrichment"],
    dependencies=[Depends(require_role("admin"))],
)


@router.get("/enrichment/ceilings", response_model=list[CeilingRow])
async def list_ceilings(db: AsyncSession = Depends(get_session)) -> list[CeilingRow]:
    period = credits.current_period()
    rows: list[CeilingRow] = []
    for provider in METERED_PROVIDERS:
        limit = await credits.get_ceiling(db, provider)
        used = await credits.get_usage(db, provider, period)
        rows.append(
            CeilingRow(
                provider=provider,
                monthly_limit=limit,
                used=used,
                remaining=(None if limit <= 0 else max(0, limit - used)),
                pct=credits.usage_pct(used, limit),
                period=period,
            )
        )
    return rows


@router.put("/enrichment/ceilings/{provider}", response_model=CeilingRow)
async def set_ceiling(
    provider: str,
    payload: CeilingUpdate,
    db: AsyncSession = Depends(get_session),
) -> CeilingRow:
    p = (provider or "").strip().lower()
    if p not in METERED_PROVIDERS:
        raise HTTPException(status_code=400, detail="unknown provider")
    limit = await credits.set_ceiling(db, p, payload.monthly_limit)
    period = credits.current_period()
    used = await credits.get_usage(db, p, period)
    return CeilingRow(
        provider=p,
        monthly_limit=limit,
        used=used,
        remaining=(None if limit <= 0 else max(0, limit - used)),
        pct=credits.usage_pct(used, limit),
        period=period,
    )
