"""Job CRUD + progress helpers — the only place that mutates a Job row.

Pure DB I/O, no network. Feature modules call these from inside their work
coroutine to report progress; the router reads them for the popup. Counters are
integers (no floats). Every mutation commits so a polling client sees fresh
state immediately.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import JobOut
from app.jobs.orm import Job


def to_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        campaign_id=job.campaign_id,
        kind=job.kind,
        status=job.status,
        total=job.total or 0,
        processed=job.processed or 0,
        created_count=job.created_count or 0,
        skipped_count=job.skipped_count or 0,
        error_count=job.error_count or 0,
        credits_used=job.credits_used or 0,
        message=job.message,
        detail=job.detail,
        created_at=job.created_at.isoformat() if job.created_at else "",
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        updated_at=job.updated_at.isoformat() if job.updated_at else "",
    )


async def create_job(
    db: AsyncSession, *, kind: str, campaign_id: int | None, message: str | None = None
) -> Job:
    """Create a pending job and commit so the client can poll it at once."""
    job = Job(kind=kind, campaign_id=campaign_id, status="pending", message=message)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def mark_running(
    db: AsyncSession, job_id: int, *, total: int = 0, message: str | None = None
) -> None:
    from sqlalchemy import func as _func

    job = await db.get(Job, job_id)
    if job is None:
        return
    job.status = "running"
    job.total = int(total)
    job.started_at = _func.now()
    if message is not None:
        job.message = message
    await db.commit()


async def update_progress(db: AsyncSession, job_id: int, **fields) -> None:
    """Set any of the integer counters / message on a running job.

    Accepts absolute values for: processed, created_count, skipped_count,
    error_count, credits_used, total, message. Caller passes the current totals
    (deterministic, no read-modify race within a single-task job).
    """
    job = await db.get(Job, job_id)
    if job is None:
        return
    for key in (
        "processed",
        "created_count",
        "skipped_count",
        "error_count",
        "credits_used",
        "total",
    ):
        if key in fields and fields[key] is not None:
            setattr(job, key, int(fields[key]))
    if fields.get("message") is not None:
        job.message = fields["message"]
    if fields.get("detail") is not None:
        job.detail = fields["detail"]
    await db.commit()


async def mark_done(db: AsyncSession, job_id: int, *, message: str | None = None) -> None:
    from sqlalchemy import func as _func

    job = await db.get(Job, job_id)
    if job is None:
        return
    job.status = "done"
    job.finished_at = _func.now()
    if message is not None:
        job.message = message
    await db.commit()


async def mark_error(db: AsyncSession, job_id: int, message: str) -> None:
    from sqlalchemy import func as _func

    job = await db.get(Job, job_id)
    if job is None:
        return
    job.status = "error"
    job.finished_at = _func.now()
    job.message = message
    await db.commit()


async def mark_paused(db: AsyncSession, job_id: int, *, message: str | None = None) -> None:
    """Gracefully pause a running job (resumable — no finished_at)."""
    job = await db.get(Job, job_id)
    if job is None:
        return
    job.status = "paused"
    if message is not None:
        job.message = message
    await db.commit()


async def mark_cancelled(db: AsyncSession, job_id: int, *, message: str | None = None) -> None:
    """Stop a job PERMANENTLY (terminal, NOT resumable). Partial work already persisted
    stays (no data loss); the job just won't be resumed, so the next run starts fresh."""
    from sqlalchemy import func as _func

    job = await db.get(Job, job_id)
    if job is None:
        return
    job.status = "cancelled"
    job.finished_at = _func.now()
    if message is not None:
        job.message = message
    await db.commit()


async def get_job(db: AsyncSession, job_id: int) -> Job | None:
    return await db.get(Job, job_id)


async def latest_resumable(db: AsyncSession, *, campaign_id: int | None, kind: str) -> Job | None:
    """Newest job that is still in-flight OR paused — so a popup can reattach and
    offer Resume after a close/reload."""
    stmt = (
        select(Job)
        .where(
            Job.campaign_id == campaign_id,
            Job.kind == kind,
            Job.status.in_(("pending", "running", "paused")),
        )
        .order_by(Job.id.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def latest_job(
    db: AsyncSession, *, campaign_id: int, kind: str
) -> Job | None:
    """Newest job for a campaign+kind — lets the popup reappear after reload."""
    stmt = (
        select(Job)
        .where(Job.campaign_id == campaign_id, Job.kind == kind)
        .order_by(Job.id.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def active_job(db: AsyncSession, *, campaign_id: int, kind: str) -> Job | None:
    """A pending/running job for this campaign+kind, if any (dedupe clicks)."""
    stmt = (
        select(Job)
        .where(
            Job.campaign_id == campaign_id,
            Job.kind == kind,
            Job.status.in_(("pending", "running")),
        )
        .order_by(Job.id.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()
