"""Read-only cost-estimator endpoint (admin-only).

GET /api/cost/estimate?emails=&rate=&sending_days=
    Returns the monthly cost breakdown in USD + INR for a given email volume
    and USD->INR rate. Pure computation over fixed vendor constants — no DB
    read/write, no pipeline state touched. Admin-only (matches Catalog / API
    keys / Budget tabs; cost figures are financial).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.permissions import require_role
from app.cost.calculator import compute_estimate
from app.cost.models import CostEstimate

router = APIRouter(
    prefix="/api/cost",
    tags=["cost"],
    dependencies=[Depends(require_role("admin"))],
)


@router.get("/estimate", response_model=CostEstimate)
async def estimate(
    emails: int = Query(6000, ge=1, le=10_000_000),
    rate: Decimal = Query(Decimal("86"), gt=0, le=10_000),
    sending_days: int = Query(30, ge=1, le=31),
) -> CostEstimate:
    try:
        result = compute_estimate(emails=emails, rate=rate, sending_days=sending_days)
    except (ValueError, InvalidOperation) as exc:  # defensive; Query already guards
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CostEstimate(**result)
