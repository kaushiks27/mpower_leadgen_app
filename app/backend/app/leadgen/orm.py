"""Generate-Leads ORM — one new table tracking a Generate-Leads run.

Per OP #11 the feature table lives here, never in `app/db/models.py`. Registered
on the shared `Base.metadata` via `app/db/__init__.py:init_db`.

`LeadgenRun` ties a background Job to its request params + the per-customer
processing state, so a paused/orphaned run can RESUME over the customers still
marked "pending" (never re-running the ones already "done"). Soft state only —
nothing here is a load-bearing money/pipeline number.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, Text, func

from app.db.models import Base


class LeadgenRun(Base):
    __tablename__ = "leadgen_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, nullable=False, index=True)
    # The GenerateRequest as submitted (json.dumps) — the resume row-set source.
    params_json = Column(Text, nullable=True)
    # {customer_id: "pending"|"done"|"error"} (json.dumps). Drives resume.
    customer_states_json = Column(Text, nullable=True)
    # {customer_id: "approved"|"skipped"} (json.dumps) — the user's per-company
    # decision on the Claude "widen" confirmation prompt. Absent = not yet asked.
    widen_states_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
