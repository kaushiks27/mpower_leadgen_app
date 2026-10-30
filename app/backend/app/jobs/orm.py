"""SQLAlchemy ORM for the background-job infrastructure.

Per OP #11 this is INFRASTRUCTURE: it imports only `app.db`. Feature modules
(`scraping`, `enrichment`) enqueue work and own the work coroutine; `jobs`
imports nothing from them. One row tracks one background run so a closed/reopened
browser tab can re-read live progress (the run keeps going server-side).

All counters are plain integers (no money/floats). Soft state only — nothing
here is a load-bearing pipeline decision.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.db.models import Base

# Job kinds. SSOT — feature modules + router + frontend mirror these strings.
JOB_KINDS = (
    "generate_leads", "apollo_enrich", "icebreaker", "instantly_push", "competitors_sync",
    "customers_sync",
)

# Lifecycle. pending -> running -> (done | error). A long run may also be
# gracefully PAUSED (resumable): running -> paused -> (running again | …).
JOB_STATUSES = ("pending", "running", "done", "error", "paused")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Which campaign this run belongs to (every S-6 job is campaign-scoped).
    campaign_id = Column(Integer, nullable=True, index=True)
    kind = Column(String(32), nullable=False, index=True)  # JOB_KINDS
    status = Column(String(16), nullable=False, server_default="pending")  # JOB_STATUSES

    # Live progress counters (integers only).
    total = Column(Integer, nullable=False, server_default="0")
    processed = Column(Integer, nullable=False, server_default="0")
    created_count = Column(Integer, nullable=False, server_default="0")
    skipped_count = Column(Integer, nullable=False, server_default="0")
    error_count = Column(Integer, nullable=False, server_default="0")
    credits_used = Column(Integer, nullable=False, server_default="0")

    # Human-readable one-liner shown in the popup; `detail` holds an optional
    # JSON blob (e.g. per-provider credit breakdown) for richer display.
    message = Column(Text, nullable=True)
    detail = Column(Text, nullable=True)  # json.dumps, optional

    created_at = Column(DateTime, default=func.now(), nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
