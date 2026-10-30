"""Pydantic V2 shapes for /api/jobs/*. All counters are integers."""

from __future__ import annotations

from pydantic import BaseModel


class JobOut(BaseModel):
    """Live snapshot of one background run, polled by the progress popup."""

    id: int
    campaign_id: int | None = None
    kind: str
    status: str  # pending | running | done | error
    total: int
    processed: int
    created_count: int
    skipped_count: int
    error_count: int
    credits_used: int
    message: str | None = None
    detail: str | None = None  # optional JSON blob (e.g. {"stage":N,"current":"…"})
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str
