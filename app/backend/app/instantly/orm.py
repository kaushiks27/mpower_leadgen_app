"""SQLAlchemy ORM for the Instantly push feature (S-8).

Per OP #11 feature tables live here — never in `app/db/models.py`. Registered on
the shared `Base.metadata` via `app/db/__init__.py:init_db`.

One row per app campaign that has been pushed (or attempted) to Instantly. The
absence of a row = "not pushed". `instantly_campaign_id` is the UUID Instantly
returns on create; it is the map app-campaign → Instantly-campaign (one-to-one).
Soft state only — counters are integers (no money/floats); nothing here is an
LLM decision. Re-push is blocked once a row exists (locked after create, S-8).
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)

from app.db.models import Base

# Persisted push lifecycle. "not_pushed" is represented by NO row (never stored).
#   draft -> created in Instantly, not yet started (mailboxes attached externally)
#   live  -> activated (Start pressed); Instantly is sending
#   error -> a create/start call failed; error message held in `error`
PUSH_STATUSES = ("draft", "live", "error")


class InstantlyCampaign(Base):
    __tablename__ = "instantly_campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # One row per app campaign (unique). FK keeps it tied to the source campaign.
    campaign_id = Column(
        Integer, ForeignKey("campaigns.id"), nullable=False, unique=True, index=True
    )

    # Instantly's campaign UUID (set once create succeeds). Null while a create is
    # mid-flight or failed before returning an id.
    instantly_campaign_id = Column(String(64), nullable=True)

    status = Column(String(16), nullable=False, server_default="draft")  # PUSH_STATUSES

    # Last error surfaced to the UI pill (create/start failure). Cleared on success.
    error = Column(Text, nullable=True)

    # Push result counters (integers only — never money/float).
    leads_pushed = Column(Integer, nullable=False, server_default="0")
    leads_failed = Column(Integer, nullable=False, server_default="0")

    pushed_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class InstantlySyncState(Base):
    """Last Instantly-pull (Sync) result per app campaign (S-9).

    A SEPARATE table (not new columns on `instantly_campaigns`) on purpose: the dev
    SQLite DB is persistent (OP #13) and `create_all` adds new TABLES but never
    ALTERs an existing one, so a fresh table is the no-migration way to add pull
    state without touching the push row. One row per campaign (unique). Counters are
    integers only — no money/float, no LLM decision. The authoritative pipeline
    state still lives on the leads themselves; this row is just the Sync summary +
    timestamp the Monitor shows.
    """

    __tablename__ = "instantly_sync_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(
        Integer, ForeignKey("campaigns.id"), nullable=False, unique=True, index=True
    )

    last_synced_at = Column(DateTime, nullable=True)

    # Last-run summary (integers only).
    leads_pulled = Column(Integer, nullable=False, server_default="0")
    leads_matched = Column(Integer, nullable=False, server_default="0")
    leads_unmatched = Column(Integer, nullable=False, server_default="0")
    replies = Column(Integer, nullable=False, server_default="0")
    bounces = Column(Integer, nullable=False, server_default="0")
    unsubscribes = Column(Integer, nullable=False, server_default="0")

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
