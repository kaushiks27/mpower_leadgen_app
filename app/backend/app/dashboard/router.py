"""Read-only dashboard endpoint (any signed-in user).

GET /api/dashboard/summary
    Funnel counts + reply/positive rates per campaign (+ All-campaigns total),
    5,000/month goal progress, Apollo/MillionVerifier credit burn, and the
    hot-reply action queue. Pure aggregation over persisted tables — no DB
    writes, no live external calls, no LLM-computed numbers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.dashboard.aggregator import build_summary
from app.dashboard.models import DashboardSummary
from app.db import get_session

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],  # any signed-in user (admin or rep)
)


@router.get("/summary", response_model=DashboardSummary)
async def summary(db: AsyncSession = Depends(get_session)) -> DashboardSummary:
    return await build_summary(db)
