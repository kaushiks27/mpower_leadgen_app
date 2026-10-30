"""Fire-and-forget background runner — the reason jobs survive a closed tab.

`launch(job_id, work)` schedules `work` on the event loop with `create_task` and
returns immediately, so the HTTP handler responds with the job id while the work
keeps running server-side regardless of the client. A strong reference to each
task is held until it finishes (so the loop never GCs a running task), and any
uncaught exception flips the job to `error` with the message.

Single-process app (one uvicorn worker) — no external queue is warranted (that
would be over-engineering per OP #11). If the process restarts mid-run the job
is left `running`; the work is idempotent (per-lead `enriched_at` guards against
double-spend), so the user just re-clicks.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.service import mark_error

logger = logging.getLogger(__name__)

# Work gets a fresh session + the job id; it owns its own progress reporting.
Work = Callable[[AsyncSession, int], Awaitable[None]]

# Hold references so the event loop doesn't garbage-collect a running task.
_TASKS: set[asyncio.Task] = set()

# Liveness registry: job_id -> its in-flight task. Lets a router tell a GENUINELY
# running job (dedupe a double-click) apart from an ORPHANED one whose worker died
# (a process restart — dev --reload OR a prod redeploy — kills the task but leaves
# the job row "running"). After a restart this dict is empty, so every prior
# "running" job is correctly seen as not-live → resumable. In-process (single
# uvicorn worker); precise within the process, conservatively empty across restarts.
_LIVE: dict[int, asyncio.Task] = {}


def is_live(job_id: int) -> bool:
    """True iff a background task for this job is alive IN THIS PROCESS right now."""
    return job_id in _LIVE

# Cooperative-pause registry. A feature's work coroutine checks `is_paused(job_id)`
# between items and exits gracefully (marking the job 'paused'); the partial,
# idempotent work is already persisted, so resuming = launching the job again,
# which continues on whatever is left. In-process (single uvicorn worker); a
# process restart clears it, which is safe (a paused job row persists and resumes).
_PAUSE: set[int] = set()


def request_pause(job_id: int) -> None:
    """Ask a running job to stop gracefully at its next checkpoint."""
    _PAUSE.add(job_id)


def is_paused(job_id: int) -> bool:
    return job_id in _PAUSE


def clear_pause(job_id: int) -> None:
    """Clear any stale pause flag (called when a job (re)starts)."""
    _PAUSE.discard(job_id)


# Cooperative-cancel registry (parallel to pause). A worker checks
# `is_cancelled(job_id)` at its checkpoint and stops PERMANENTLY (marks the job
# done/cancelled, leaving no resumable "pending" work) rather than pausing — so a
# fresh run starts clean. In-process; a restart clears it (safe: the endpoint also
# marks the job terminal directly when no live worker is running).
_CANCEL: set[int] = set()


def request_cancel(job_id: int) -> None:
    """Ask a running job to stop permanently at its next checkpoint."""
    _CANCEL.add(job_id)


def is_cancelled(job_id: int) -> bool:
    return job_id in _CANCEL


def clear_cancel(job_id: int) -> None:
    """Clear any stale cancel flag (called when a job (re)starts)."""
    _CANCEL.discard(job_id)


async def _guarded(job_id: int, work: Work) -> None:
    import app.db as db_mod

    try:
        async with db_mod.async_session() as db:
            await work(db, job_id)
    except Exception as e:  # noqa: BLE001 — any failure must surface on the job
        logger.exception("job %s failed", job_id)
        try:
            async with db_mod.async_session() as db2:
                await mark_error(db2, job_id, f"{type(e).__name__}: {e}")
        except Exception:  # pragma: no cover — last-resort guard
            logger.exception("could not mark job %s as error", job_id)


def launch(job_id: int, work: Work) -> None:
    """Schedule `work` in the background and return immediately."""
    task = asyncio.create_task(_guarded(job_id, work))
    _TASKS.add(task)
    _LIVE[job_id] = task

    def _done(t: asyncio.Task) -> None:
        _TASKS.discard(t)
        if _LIVE.get(job_id) is t:  # don't evict a newer task for the same job id
            del _LIVE[job_id]

    task.add_done_callback(_done)


async def run_now(job_id: int, work: Work) -> None:
    """Run `work` to completion in the current task (used by tests).

    Same error-handling contract as `launch`, but awaited inline so a test can
    assert on the final job state without racing a background task.
    """
    await _guarded(job_id, work)
