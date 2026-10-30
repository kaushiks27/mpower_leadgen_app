"""Master Leads-page icebreaker endpoint (admin-only).

POST /api/leads/icebreaker   start a background icebreaker job over selected leads

08062026_cr CR-2: the AI "Create Icebreaker" action moved OFF the campaign page
(its lead-gen buttons were removed) ONTO the master Leads list, where it runs on
an explicit selection of verified leads. Generation runs only via the launched
background job, triggered by an explicit user click. A missing Anthropic key /
nothing-to-write returns a clean 400 — never a raw 500.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import require_role
from app.db import get_session
from app.email_gen.models import LeadIcebreakerRequest
from app.email_gen.service import _missing_leads_by_ids, run_icebreaker_job_for_leads
from app.jobs import runner
from app.jobs import service as jobs_service
from app.jobs.models import JobOut
from app.settings.keys import resolve_api_key

router = APIRouter(
    prefix="/api",
    tags=["email_gen"],
    dependencies=[Depends(require_role("admin"))],
)


@router.post("/leads/icebreaker", response_model=JobOut)
async def generate_lead_icebreakers(
    payload: LeadIcebreakerRequest,
    db: AsyncSession = Depends(get_session),
) -> JobOut:
    lead_ids = [int(i) for i in (payload.lead_ids or [])]
    if not lead_ids:
        raise HTTPException(status_code=400, detail="Select at least one lead.")

    # Reuse an in-flight master icebreaker job so a double-click never launches two.
    existing = await jobs_service.active_job(
        db, campaign_id=None, kind="icebreaker"
    )
    if existing is not None:
        return jobs_service.to_out(existing)

    if not resolve_api_key("anthropic"):
        raise HTTPException(
            status_code=400,
            detail="Anthropic (Claude) API key not set — add it in Settings.",
        )

    missing = await _missing_leads_by_ids(db, lead_ids)
    if not missing:
        raise HTTPException(
            status_code=400,
            detail=(
                "No selected lead needs an icebreaker — pick verified leads "
                "(SalesPath Sure/Likely) that don't already have one."
            ),
        )

    job = await jobs_service.create_job(
        db, kind="icebreaker", campaign_id=None, message="Queued…"
    )

    async def _work(work_db: AsyncSession, job_id: int) -> None:
        await run_icebreaker_job_for_leads(work_db, job_id, lead_ids)

    runner.launch(job.id, _work)
    return jobs_service.to_out(job)
