"""Generate-Leads engine endpoints (admin-only).

GET  /api/leadgen/lists      categories + types + countries + customers + roles
GET  /api/leadgen/customers  customers filtered by ?categories=&type=&country=
GET  /api/leadgen/roles      the decision-maker role taxonomy
POST /api/leadgen/generate   start (or resume) a Generate-Leads run → JobOut
GET  /api/leadgen/active     the in-flight / paused run (popup reattach)
POST /api/leadgen/pause      ask the in-flight run to stop gracefully
POST /api/leadgen/cancel     permanently cancel the run so the next click is fresh
GET  /api/leadgen/dev-info   read-only actors + sample input + the widen prompt

Admin-only. The run executes only via the launched background job, on an explicit
click. ≥1 customer + ≥1 role group + an Apify key are required to start.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import require_role
from app.db import get_session
from app.jobs import runner
from app.jobs import service as jobs_service
from app.jobs.models import JobOut
from app.leadgen import service
from app.leadgen.models import (
    CustomerLite,
    DevInfo,
    GenerateRequest,
    ListsResponse,
    RoleGroupOut,
    WidenRequest,
)
from app.settings.keys import resolve_api_key

router = APIRouter(
    prefix="/api/leadgen",
    tags=["leadgen"],
    dependencies=[Depends(require_role("admin"))],
)

_KIND = service.JOB_KIND


def _csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


@router.get("/lists", response_model=ListsResponse)
async def lists(db: AsyncSession = Depends(get_session)) -> ListsResponse:
    return ListsResponse(**await service.assemble_lists(db))


@router.get("/customers", response_model=list[CustomerLite])
async def customers(
    categories: str | None = Query(default=None),
    type: str | None = Query(default=None),  # noqa: A002 — query name, comma-separated
    country: str | None = Query(default=None),
    bands: str | None = Query(default=None),  # CR-1: Sure/Likely allow-list (CSV)
    db: AsyncSession = Depends(get_session),
) -> list[CustomerLite]:
    return await service.get_filtered_customers(
        db, _csv(categories), _csv(type), country, _csv(bands)
    )


@router.get("/roles", response_model=list[RoleGroupOut])
async def roles() -> list[RoleGroupOut]:
    return service.get_roles()


@router.get("/dev-info", response_model=DevInfo)
async def dev_info() -> DevInfo:
    return service.dev_info()


@router.get("/active")
async def active(db: AsyncSession = Depends(get_session)) -> dict:
    job = await jobs_service.latest_resumable(db, campaign_id=None, kind=_KIND)
    return {"job": jobs_service.to_out(job) if job else None}


@router.post("/pause")
async def pause(db: AsyncSession = Depends(get_session)) -> dict:
    """Ask the in-flight run to stop gracefully; mark an ORPHANED worker paused now."""
    job = await jobs_service.active_job(db, campaign_id=None, kind=_KIND)
    if job is not None:
        if runner.is_live(job.id):
            runner.request_pause(job.id)
        else:
            await jobs_service.mark_paused(
                db, job.id,
                message="Paused (the worker had stopped). Resume to continue.",
            )
            await db.refresh(job)
    return {"job": jobs_service.to_out(job) if job else None}


@router.post("/widen")
async def widen(payload: WidenRequest, db: AsyncSession = Depends(get_session)) -> dict:
    """Record the user's widen decision for the saturated company, then resume.

    approve=True (needs an Anthropic key) → Claude rewrites the saturated query
    to surface ~50% more decision-makers. approve=False → continue with the thin
    results. Either way the paused run resumes.
    """
    job = await jobs_service.get_job(db, payload.job_id)
    if job is None or job.kind != _KIND:
        raise HTTPException(status_code=404, detail="Generate-Leads run not found.")
    if payload.approve and not resolve_api_key("anthropic"):
        raise HTTPException(
            status_code=400,
            detail="Anthropic API key not set — needed to widen the search.",
        )
    cid = await service.set_widen_decision(db, payload.job_id, approve=payload.approve)
    if cid is None:
        raise HTTPException(
            status_code=400, detail="This run is not waiting for a widen decision."
        )
    service.resume_run(payload.job_id, runner=runner)
    await db.refresh(job)
    return {"job": jobs_service.to_out(job)}


@router.post("/cancel")
async def cancel(db: AsyncSession = Depends(get_session)) -> dict:
    """Permanently cancel the current run so the next Generate starts fresh."""
    jid = await service.cancel_run(db, runner=runner)
    return {"cancelled_job_id": jid}


@router.post("/generate", response_model=JobOut)
async def generate(
    payload: GenerateRequest, db: AsyncSession = Depends(get_session)
) -> JobOut:
    if not payload.customer_ids:
        raise HTTPException(status_code=400, detail="Select at least one customer.")
    if not payload.role_groups:
        raise HTTPException(status_code=400, detail="Select at least one role group.")
    if not resolve_api_key("apify"):
        raise HTTPException(
            status_code=400, detail="Apify API key not set — add it in Settings."
        )
    job = await service.start_run(db, payload, runner=runner)
    return jobs_service.to_out(job)
