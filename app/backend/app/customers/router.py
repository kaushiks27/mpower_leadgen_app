"""mPower's Brain — Customers endpoints (admin-only).

GET    /api/brain/customers             list (optional ?scope=local|global & ?include_archived=)
GET    /api/brain/customers/summary     counts + last-synced
GET    /api/brain/customers/categories  the live mPower catalog category set
GET    /api/brain/customers/dev-info    read-only discovery strategy + Claude prompt
GET    /api/brain/customers/active-sync in-flight OR paused sync job (popup reattach)
POST   /api/brain/customers            manually add a customer (protected from sync)
PATCH  /api/brain/customers/{id}       inline-edit (each edited field locks vs sync)
POST   /api/brain/customers/sync       start a fresh sync OR RESUME a paused one
POST   /api/brain/customers/sync/pause ask the in-flight sync to stop gracefully

Admin-only. Sync runs only via the launched background job, on an explicit click.
Manual rows + edited fields are never overwritten by a sync.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import require_role
from app.customers import claude_classify, config, service, sourcing, sync
from app.customers.models import (
    ActiveSyncOut,
    CustomerDevInfo,
    CustomerOut,
    CustomerSummary,
    EditRequest,
    ManualAddRequest,
    SyncRequest,
)
from app.customers.sync import resume_sync_job, run_sync_job
from app.db import get_session
from app.jobs import runner
from app.jobs import service as jobs_service
from app.jobs.models import JobOut

router = APIRouter(
    prefix="/api/brain/customers",
    tags=["customers"],
    dependencies=[Depends(require_role("admin"))],
)

_SYNC_KIND = "customers_sync"


@router.get("", response_model=list[CustomerOut])
async def list_customers(
    scope: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
) -> list[CustomerOut]:
    items = await service.list_customers(
        db, scope=scope, include_archived=include_archived
    )
    return [service.to_out(i) for i in items]


@router.get("/summary", response_model=CustomerSummary)
async def customer_summary(db: AsyncSession = Depends(get_session)) -> CustomerSummary:
    return CustomerSummary(**await service.summary(db))


@router.get("/categories", response_model=list[str])
async def categories(db: AsyncSession = Depends(get_session)) -> list[str]:
    """The live Products & Services category set (used by the Category column + manual add)."""
    return await service.mpower_categories(db)


@router.get("/dev-info", response_model=CustomerDevInfo)
async def dev_info(db: AsyncSession = Depends(get_session)) -> CustomerDevInfo:
    """Read-only: the real discovery sources/queries + the Claude classifier prompt."""
    cats = await service.mpower_categories(db)
    return CustomerDevInfo(
        search_actor=config.SEARCH_ACTOR,
        crawl_actor=config.CRAWL_ACTOR,
        sources=[f"{label} — {hint}" for label, hint in config.DISCOVERY_SOURCES],
        type_sources=list(config.TYPE_SOURCES),
        sample_queries=sourcing.seed_queries(cats, 0),
        enrichment_queries=sourcing.profile_queries("<Customer>", "<customer>.com"),
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


@router.post("", response_model=CustomerOut, status_code=201)
async def add_customer(
    payload: ManualAddRequest, db: AsyncSession = Depends(get_session)
) -> CustomerOut:
    try:
        item = await service.add_manual(
            db, name=payload.name, website=payload.website,
            country=payload.country, category=payload.category,
            ctype=payload.ctype,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return service.to_out(item)


@router.patch("/{item_id}", response_model=CustomerOut)
async def edit_customer(
    item_id: int, payload: EditRequest, db: AsyncSession = Depends(get_session)
) -> CustomerOut:
    item = await service.edit_customer(
        db, item_id,
        name=payload.name, website=payload.website, country=payload.country,
        category=payload.category, ctype=payload.ctype,
        archived=payload.archived,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="customer not found")
    return service.to_out(item)


@router.post("/sync", response_model=JobOut)
async def sync_customers(
    payload: SyncRequest,
    db: AsyncSession = Depends(get_session),
) -> JobOut:
    # 1) GENUINELY running (a live worker) → return it (dedupe double-clicks).
    running = await jobs_service.active_job(db, campaign_id=None, kind=_SYNC_KIND)
    if running is not None and runner.is_live(running.id):
        return jobs_service.to_out(running)

    # 2) A PAUSED or ORPHANED job exists → RESUME it: skip discovery, finish the
    #    remaining rows. "Orphaned" = status running but no live worker (its task died
    #    on a process restart). This fixes both "Resume starts over" AND a stuck sync
    #    after a redeploy/--reload — a fresh run_sync_job would re-run stage-1 discovery.
    resumable = await jobs_service.latest_resumable(db, campaign_id=None, kind=_SYNC_KIND)
    if resumable is not None and not runner.is_live(resumable.id):
        runner.clear_pause(resumable.id)

        async def _resume(work_db: AsyncSession, job_id: int) -> None:
            await resume_sync_job(work_db, job_id)

        runner.launch(resumable.id, _resume)
        return jobs_service.to_out(resumable)

    # 3) Otherwise → a fresh full sync. `per_source` = companies pulled from EACH
    #    source/lane (popup knob, default 50).
    per_source = payload.per_source
    job = await jobs_service.create_job(
        db, kind=_SYNC_KIND, campaign_id=None, message="Queued…"
    )

    async def _work(work_db: AsyncSession, job_id: int) -> None:
        await run_sync_job(work_db, job_id, per_source=per_source)

    runner.launch(job.id, _work)
    return jobs_service.to_out(job)
