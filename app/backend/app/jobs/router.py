"""Read-only job-status endpoints for the progress popup.

GET /api/jobs/{id}                          one job snapshot
GET /api/jobs?campaign_id=&kind=&latest=1   latest job for a campaign+kind

Any signed-in user may read job status (matches leads being shared). Jobs are
created only by the feature routers (scraping/enrichment), never here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db import get_session
from app.jobs.models import JobOut
from app.jobs.orm import JOB_KINDS
from app.jobs.service import get_job, latest_job, to_out

router = APIRouter(
    prefix="/api/jobs",
    tags=["jobs"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/{job_id}", response_model=JobOut)
async def read_job(job_id: int, db: AsyncSession = Depends(get_session)) -> JobOut:
    job = await get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return to_out(job)


@router.get("", response_model=JobOut | None)
async def read_latest(
    campaign_id: int = Query(...),
    kind: str = Query(...),
    db: AsyncSession = Depends(get_session),
) -> JobOut | None:
    if kind not in JOB_KINDS:
        raise HTTPException(status_code=400, detail=f"unknown job kind: {kind}")
    job = await latest_job(db, campaign_id=campaign_id, kind=kind)
    return to_out(job) if job else None
