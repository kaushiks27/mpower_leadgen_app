"""mPower's Brain — Competitors endpoints (admin-only).

GET    /api/brain/competitors             list (optional ?scope=local|global & ?include_archived=)
GET    /api/brain/competitors/summary     counts + last-synced
GET    /api/brain/competitors/categories  the live mPower catalog category set
GET    /api/brain/competitors/dev-info    read-only discovery strategy + Claude prompt
GET    /api/brain/competitors/active-sync in-flight sync job (popup reattach)
POST   /api/brain/competitors            manually add a competitor (protected from sync)
PATCH  /api/brain/competitors/{id}       inline-edit (each edited field locks vs sync)
POST   /api/brain/competitors/sync       start the background discover+classify job

Admin-only (matches the Products & Services surface). Sync runs only via the
launched background job, on an explicit click. Manual rows + edited fields are
never overwritten by a sync.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import require_role
from app.competitors import claude_classify, config, service, sourcing, sync
from app.competitors.models import (
    ActiveSyncOut,
    CompetitorDevInfo,
    CompetitorOut,
    CompetitorSummary,
    EditRequest,
    ManualAddRequest,
    SyncRequest,
)
from app.competitors.sync import resume_sync_job, run_sync_job
from app.db import get_session
from app.jobs import runner
from app.jobs import service as jobs_service
from app.jobs.models import JobOut

router = APIRouter(
    prefix="/api/brain/competitors",
    tags=["competitors"],
    dependencies=[Depends(require_role("admin"))],
)

_SYNC_KIND = "competitors_sync"


@router.get("", response_model=list[CompetitorOut])
async def list_competitors(
    scope: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
) -> list[CompetitorOut]:
    items = await service.list_competitors(
        db, scope=scope, include_archived=include_archived
    )
    return [service.to_out(i) for i in items]


@router.get("/summary", response_model=CompetitorSummary)
async def competitor_summary(db: AsyncSession = Depends(get_session)) -> CompetitorSummary:
    return CompetitorSummary(**await service.summary(db))


@router.get("/categories", response_model=list[str])
async def categories(db: AsyncSession = Depends(get_session)) -> list[str]:
    """The live Products & Services category set (used by the Category column + manual add)."""
    return await service.mpower_categories(db)


@router.get("/dev-info", response_model=CompetitorDevInfo)
async def dev_info(db: AsyncSession = Depends(get_session)) -> CompetitorDevInfo:
    """Read-only: the real discovery sources/queries + the Claude classifier prompt."""
    cats = await service.mpower_categories(db)
    return CompetitorDevInfo(
        search_actor=config.SEARCH_ACTOR,
        crawl_actor=config.CRAWL_ACTOR,
        sources=[f"{label} — {hint}" for label, hint in config.DISCOVERY_SOURCES],
        selling_to_sources=list(config.SELLING_TO_SOURCES),
        sample_queries=sourcing.seed_queries(cats, 0),
        enrichment_queries=sourcing.profile_queries("<Competitor>", "<competitor>.com"),
        mpower_categories=cats,
        pipeline_steps=[f"{n}. {label}" for n, label in sorted(sync.STAGE_LABELS.items())],
        claude_model=claude_classify.DEFAULT_MODEL,
        claude_system=claude_classify.SYSTEM,
        claude_user_template=claude_classify.USER_TEMPLATE,
        extract_model=config.EXTRACT_MODEL,
        extract_system=claude_classify.EXTRACT_SYSTEM,
        extract_user_template=claude_classify.EXTRACT_USER_TEMPLATE,
    )


@router.get("/active-sync", response_model=ActiveSyncOut)
async def active_sync(db: AsyncSession = Depends(get_session)) -> ActiveSyncOut:
    # running OR paused → the popup reattaches and can offer Resume.
    job = await jobs_service.latest_resumable(db, campaign_id=None, kind=_SYNC_KIND)
    return ActiveSyncOut(job=jobs_service.to_out(job) if job else None)


@router.post("/sync/pause", response_model=ActiveSyncOut)
async def pause_sync(db: AsyncSession = Depends(get_session)) -> ActiveSyncOut:
    """Ask the in-flight sync to stop gracefully at its next checkpoint. Partial,
    idempotent work is kept; Resume (POST /sync) continues on what's left.

    If the worker is ORPHANED (its task died on a process restart — dev --reload or a
    prod redeploy), there is nothing to cooperatively stop, so mark it paused at once
    (otherwise "Pausing…" would hang forever). Resume then continues the remaining rows."""
    job = await jobs_service.active_job(db, campaign_id=None, kind=_SYNC_KIND)
    if job is not None:
        if runner.is_live(job.id):
            runner.request_pause(job.id)  # alive → graceful cooperative pause
        else:
            await jobs_service.mark_paused(
                db, job.id,
                message="Paused (the sync worker had stopped). Resume to continue from where it left off.",
            )
            await db.refresh(job)  # reload server-side onupdate cols before to_out
    return ActiveSyncOut(job=jobs_service.to_out(job) if job else None)


@router.post("/sync/cancel", response_model=ActiveSyncOut)
async def cancel_sync(db: AsyncSession = Depends(get_session)) -> ActiveSyncOut:
    """STOP the pipeline permanently. A LIVE worker is asked to cancel at its next
    checkpoint (it then marks itself terminal); an ORPHANED/paused run (no live worker
    — e.g. after a redeploy or the laptop was off) is marked terminal here directly so
    it can't hang. Partial work already done STAYS in the DB (no rows lost) — only the
    job is closed, so the NEXT Sync starts fresh instead of resuming this one."""
    job = await jobs_service.latest_resumable(db, campaign_id=None, kind=_SYNC_KIND)
    if job is not None:
        if runner.is_live(job.id):
            runner.request_cancel(job.id)  # alive → cooperative cancel at next checkpoint
        else:
            await jobs_service.mark_cancelled(
                db, job.id, message="Stopped by you. Next Sync starts fresh.",
            )
            runner.clear_pause(job.id)
            runner.clear_cancel(job.id)
            await db.refresh(job)
    return ActiveSyncOut(job=jobs_service.to_out(job) if job else None)


@router.post("", response_model=CompetitorOut, status_code=201)
async def add_competitor(
    payload: ManualAddRequest, db: AsyncSession = Depends(get_session)
) -> CompetitorOut:
    try:
        item = await service.add_manual(
            db, name=payload.name, website=payload.website,
            country=payload.country, category=payload.category,
            selling_to=payload.selling_to,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return service.to_out(item)


@router.patch("/{item_id}", response_model=CompetitorOut)
async def edit_competitor(
    item_id: int, payload: EditRequest, db: AsyncSession = Depends(get_session)
) -> CompetitorOut:
    item = await service.edit_competitor(
        db, item_id,
        name=payload.name, website=payload.website, country=payload.country,
        category=payload.category, selling_to=payload.selling_to,
        archived=payload.archived,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="competitor not found")
    return service.to_out(item)


@router.post("/sync", response_model=JobOut)
async def sync_competitors(
    payload: SyncRequest,
    db: AsyncSession = Depends(get_session),
) -> JobOut:
    # 1) GENUINELY running (a live worker) → return it (dedupe double-clicks).
    running = await jobs_service.active_job(db, campaign_id=None, kind=_SYNC_KIND)
    if running is not None and runner.is_live(running.id):
        return jobs_service.to_out(running)

    # 2) A PAUSED or ORPHANED job exists → RESUME it: skip discovery, finish the
    #    remaining rows. "Orphaned" = status running but no live worker (its task died
    #    on a process restart). Fixes both "Resume starts over" AND a stuck sync after a
    #    redeploy/--reload — a fresh run_sync_job would re-run stage-1 discovery.
    resumable = await jobs_service.latest_resumable(db, campaign_id=None, kind=_SYNC_KIND)
    if resumable is not None and not runner.is_live(resumable.id):
        runner.clear_pause(resumable.id)

        async def _resume(work_db: AsyncSession, job_id: int) -> None:
            await resume_sync_job(work_db, job_id)

        runner.launch(resumable.id, _resume)
        return jobs_service.to_out(resumable)

    # 3) Otherwise → a fresh full sync. `per_source` = NEW companies pulled from EACH
    #    source/lane (popup knob, default 50).
    per_source = payload.per_source
    job = await jobs_service.create_job(
        db, kind=_SYNC_KIND, campaign_id=None, message="Queued…"
    )

    async def _work(work_db: AsyncSession, job_id: int) -> None:
        await run_sync_job(work_db, job_id, per_source=per_source)

    runner.launch(job.id, _work)
    return jobs_service.to_out(job)
