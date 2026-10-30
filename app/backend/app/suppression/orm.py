"""SQLAlchemy ORM for the suppression feature.

Per OP #11 feature tables live here — never in `app/db/models.py`. Registered on
the shared `Base.metadata` via `app/db/__init__.py:init_db`.

One table: `suppression_entries` — a global do-not-contact list. Each row is a
normalized identifier (email or LinkedIn URL) plus a reason. Soft-deactivate
only (`active` flag): removing an entry makes the person contactable again, so
we keep the row for auditability rather than hard-deleting.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
)

from app.db.models import Base

# Identifier kinds a suppression entry can hold. SSOT — router imports this.
SUPPRESSION_KINDS = ("email", "linkedin_url")


class SuppressionEntry(Base):
    __tablename__ = "suppression_entries"
    __table_args__ = (
        UniqueConstraint("kind", "value", name="uq_suppression_kind_value"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(16), nullable=False, index=True)  # SUPPRESSION_KINDS
    value = Column(String(320), nullable=False)  # normalized identifier
    reason = Column(String(160), nullable=True)  # e.g. manual, bounce, unsubscribe

    active = Column(Boolean, nullable=False, server_default="1", default=True)

    # Audit snapshot — who added it (survives user rename/delete).
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String(160), nullable=True)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
