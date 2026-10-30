"""Campaign-scoped Instantly push + pull endpoints (admin-only).

GET  /api/campaigns/{id}/instantly-status   button-state snapshot (push)
POST /api/campaigns/{id}/instantly-push      start a background push job (draft)
POST /api/campaigns/{id}/instantly-start     activate the pushed campaign (live)
GET  /api/instantly/monitor                  all pushed campaigns + live snapshot (pull)
POST /api/campaigns/{id}/instantly-sync      pull Instantly status → drive pipeline

Admin-only (matches campaigns/email_gen). The push runs only via the launched
background job, on an explicit click. Sync is a synchronous, idempotent read +
forward-only pipeline write. A missing key / not-pushed returns a clean 400 —
never a raw 500.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.orm import User
from app.auth.dependencies import get_current_user
from app.auth.permissions import require_role
from app.campaigns.orm import Campaign
from app.db import get_session
from app.instantly import puller
from app.instantly.models import (
    CampaignMonitor,
    InstantlyState,
    PushRequest,
    PushStatus,
    StartRequest,
    SyncRequest,
    SyncResult,
)
from app.instantly.service import PushError, push_status, run_push_job, start_campaign
from app.jobs import runner
from app.jobs import service as jobs_service
from app.jobs.models import JobOut

router = APIRouter(
    prefix="/api",
    tags=["instantly"],
    dependencies=[Depends(require_role("admin"))],
)


async def _campaign_or_404(db: AsyncSession, campaign_id: int) -> Campaign:
    c = await db.get(Campaign, campaign_id)
    if c is None or c.archived:
        raise HTTPException(status_code=404, detail="campaign not found")
    return c


@router.get(
    "/campaigns/{campaign_id}/instantly-status", response_model=PushStatus
)
async def instantly_status_endpoint(
    campaign_id: int, db: AsyncSession = Depends(get_session)
) -> PushStatus:
    campaign = await _campaign_or_404(db, campaign_id)
    return await push_status(db, campaign)


@router.post("/campaigns/{campaign_id}/instantly-push", response_model=JobOut)
async def push_campaign(
    campaign_id: int,
    payload: PushRequest,  # noqa: ARG001 — empty body; push is derived from campaign
    db: AsyncSession = Depends(get_session),
) -> JobOut:
    campaign = await _campaign_or_404(db, campaign_id)

    # Reuse an in-flight push so a double-click never launches two runs.
    existing = await jobs_service.active_job(
        db, campaign_id=campaign_id, kind="instantly_push"
    )
    if existing is not None:
        return jobs_service.to_out(existing)

    status = await push_status(db, campaign)
    if not status.can_push:
        detail = {
            "missing_key": "Instantly API key not set — add it in Settings.",
            "needs_leads": "No eligible leads yet — generate, enrich/verify, and write icebreakers first.",
            "not_ready": "Some leads aren't ready — every lead must be verified-valid with an icebreaker before pushing.",
            "already_pushed": "This campaign is already pushed to Instantly.",
        }.get(status.reason or "", "Cannot push this campaign yet.")
        raise HTTPException(status_code=400, detail=detail)

    job = await jobs_service.create_job(
        db, kind="instantly_push", campaign_id=campaign_id, message="Queued…"
    )

    async def _work(work_db: AsyncSession, job_id: int) -> None:
        await run_push_job(work_db, job_id, campaign_id)

    runner.launch(job.id, _work)
    return jobs_service.to_out(job)


@router.post(
    "/campaigns/{campaign_id}/instantly-start", response_model=InstantlyState
)
async def start_campaign_endpoint(
    campaign_id: int,
    payload: StartRequest,  # noqa: ARG001 — empty body
    db: AsyncSession = Depends(get_session),
) -> InstantlyState:
    campaign = await _campaign_or_404(db, campaign_id)
    try:
        return await start_campaign(db, campaign)
    except PushError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# --- Pull side (S-9 — Monitor / Sync) ----------------------------------------


@router.get("/instantly/monitor", response_model=list[CampaignMonitor])
async def instantly_monitor(
    db: AsyncSession = Depends(get_session),
) -> list[CampaignMonitor]:
    """All pushed campaigns with their live snapshot (no pull — derived from app)."""
    return await puller.monitor_list(db)


@router.post(
    "/campaigns/{campaign_id}/instantly-sync", response_model=SyncResult
)
async def instantly_sync(
    campaign_id: int,
    payload: SyncRequest,  # noqa: ARG001 — empty body; Sync is derived from the campaign
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> SyncResult:
    campaign = await _campaign_or_404(db, campaign_id)
    try:
        return await puller.sync_campaign(db, campaign, user=user)
    except puller.SyncError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
