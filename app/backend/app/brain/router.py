"""mPower's Brain — Products & Services catalog endpoints (admin-only).

GET    /api/brain/catalog            list items (optional ?kind= & ?include_archived=)
GET    /api/brain/catalog/summary    counts + last-synced
POST   /api/brain/catalog            manually add a row (protected from sync)
PATCH  /api/brain/catalog/{id}       edit name/price/archived
POST   /api/brain/catalog/sync       start the background Apify+Claude sync job

Admin-only (matches campaigns/settings). The sync runs only via the launched
background job, on an explicit click. Manual rows are never overwritten by sync.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import require_role
from app.brain import apify_client, claude_verify, service, sourcing
from app.brain.models import (
    ActiveSyncOut,
    CatalogDevInfo,
    CatalogItemOut,
    CatalogSummary,
    EditRequest,
    ManualAddRequest,
    SyncRequest,
)
from app.brain.sync import run_sync_job
from app.db import get_session
from app.jobs import runner
from app.jobs import service as jobs_service
from app.jobs.models import JobOut

router = APIRouter(
    prefix="/api/brain",
    tags=["brain"],
    dependencies=[Depends(require_role("admin"))],
)

_SYNC_KIND = "brain_sync"


@router.get("/catalog", response_model=list[CatalogItemOut])
async def list_catalog(
    kind: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
) -> list[CatalogItemOut]:
    items = await service.list_items(
        db, kind=kind, include_archived=include_archived
    )
    return [service.to_out(i) for i in items]


@router.get("/catalog/summary", response_model=CatalogSummary)
async def catalog_summary(db: AsyncSession = Depends(get_session)) -> CatalogSummary:
    return CatalogSummary(**await service.summary(db))


@router.get("/catalog/dev-info", response_model=CatalogDevInfo)
async def dev_info() -> CatalogDevInfo:
    """Read-only: the real Apify sourcing strategy + the Claude verifier prompt."""
    return CatalogDevInfo(
        apify_actor=apify_client.CRAWL_ACTOR,
        apify_input=json.dumps(
            apify_client.crawl_input(sourcing.MPOWER_HOME), indent=2
        ),
        products_url=sourcing.PRODUCTS_URL,
        service_slugs=list(sourcing.SERVICE_PAGES.keys()),
        claude_model=claude_verify.DEFAULT_MODEL,
        claude_system=claude_verify.SYSTEM,
        claude_user_template=claude_verify.USER_TEMPLATE,
    )


@router.get("/catalog/active-sync", response_model=ActiveSyncOut)
async def active_sync(db: AsyncSession = Depends(get_session)) -> ActiveSyncOut:
    """The in-flight sync job (if any) — lets the popup reopen after close/reload."""
    job = await jobs_service.active_job(db, campaign_id=None, kind=_SYNC_KIND)
    return ActiveSyncOut(job=jobs_service.to_out(job) if job else None)


@router.post("/catalog", response_model=CatalogItemOut, status_code=201)
async def add_item(
    payload: ManualAddRequest, db: AsyncSession = Depends(get_session)
) -> CatalogItemOut:
    try:
        item = await service.add_manual(
            db, kind=payload.kind, name=payload.name, price_inr=payload.price_inr
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return service.to_out(item)


@router.patch("/catalog/{item_id}", response_model=CatalogItemOut)
async def edit_item(
    item_id: int, payload: EditRequest, db: AsyncSession = Depends(get_session)
) -> CatalogItemOut:
    item = await service.edit_item(
        db, item_id,
        name=payload.name, price_inr=payload.price_inr, archived=payload.archived,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return service.to_out(item)


@router.post("/catalog/sync", response_model=JobOut)
async def sync_catalog(
    payload: SyncRequest,  # noqa: ARG001 — empty body; sync derived from the live site
    db: AsyncSession = Depends(get_session),
) -> JobOut:
    # Reuse an in-flight sync so a double-click never launches two runs.
    existing = await jobs_service.active_job(db, campaign_id=None, kind=_SYNC_KIND)
    if existing is not None:
        return jobs_service.to_out(existing)

    job = await jobs_service.create_job(
        db, kind=_SYNC_KIND, campaign_id=None, message="Queued…"
    )

    async def _work(work_db: AsyncSession, job_id: int) -> None:
        await run_sync_job(work_db, job_id)

    runner.launch(job.id, _work)
    return jobs_service.to_out(job)
