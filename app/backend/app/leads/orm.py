"""SQLAlchemy ORM for the leads feature.

Per OP #11 feature tables live here — never in `app/db/models.py`. Registered on
the shared `Base.metadata` via `app/db/__init__.py:init_db`.

Four-ish tables (companies + leads + lead_events; suppression lives in its own
module). Soft-archive only (OP: no lost leads); nothing is ever hard-deleted.
Every stage change writes a `lead_events` row (auditable traceability).
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.db.models import Base

# Full-funnel pipeline stages. Canonical order = board column order. SSOT —
# router + frontend mirror this. "new" is the default landing stage.
PIPELINE_STAGES = (
    "new",
    "enriched",
    "queued",
    "emailed",
    "replied",
    "interested",
    "won",
)

# Independent status flags (badges, not stages). Can co-occur.
LEAD_FLAGS = ("bounced", "unsubscribed", "not_interested")

# Audit event kinds recorded in lead_events.
EVENT_KINDS = (
    "created",
    "stage_change",
    "flag_change",
    "archived",
    "value_change",  # S-7: deal-value edit (auditable money change)
)


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    domain = Column(String(200), nullable=True)
    archived = Column(Boolean, nullable=False, server_default="0", default=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    leads = relationship("Lead", back_populates="company")


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)

    first_name = Column(String(120), nullable=False, server_default="")
    last_name = Column(String(120), nullable=False, server_default="")
    email = Column(String(320), nullable=True)
    phone = Column(String(40), nullable=True)  # optional; Apollo enrich fills it (S-6)
    linkedin_url = Column(String(400), nullable=True)
    title = Column(String(200), nullable=True)
    # `location` is repurposed (08062026_cr CR-6) to the originating customer's
    # company COUNTRY (structured), not the scraped person-city. Older rows may
    # still hold a free-text city until backfilled. Nullable.
    location = Column(String(200), nullable=True)

    # 08062026_cr CR-6 — structured taxonomy carried from the CustomerItem this
    # lead was generated from (advisory, never load-bearing). `category` mirrors
    # the brain catalog category; `customer_type` is OEM|Reseller|Distributor
    # (blank when unknown). `customer_item_id` is a nullable link to the source
    # customer for robust attribution + backfill. Additive (self-heals); no FK
    # constraint enforced (SQLite FK off) — stored as a plain nullable int.
    category = Column(String(160), nullable=True)
    customer_type = Column(String(12), nullable=True)
    customer_item_id = Column(Integer, nullable=True, index=True)

    # AI-generated one-line personalization (filled at S-7 email-gen; manual edit
    # later). Stored copy, never a load-bearing number/pipeline decision.
    icebreaker = Column(Text, nullable=True)

    # S-7: potential deal value in whole INR (exact integer rupees — no float,
    # never AI-computed). Manually entered/edited; nullable = unset. Drives the
    # pipeline board ordering (highest value first; NULLs last). A change writes a
    # `value_change` lead_event (auditable traceability — money is load-bearing).
    value_inr = Column(Integer, nullable=True)

    # S-6 enrichment/verification fields. email (above) is filled by Apollo;
    # `email_status` is the MillionVerifier verdict (valid|risky|invalid|unknown|
    # no_email) — only "valid" is Instantly-eligible (S-8). `enriched_at` set ONLY
    # after a successful Apollo call (cache/no-re-enrich + no double-charge).
    # `scrape_raw` keeps the raw scraped record (JSON) for S-7 icebreakers.
    email_status = Column(String(16), nullable=True)
    email_checked_at = Column(DateTime, nullable=True)
    enriched_at = Column(DateTime, nullable=True)
    scrape_raw = Column(Text, nullable=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)

    # S-5: the campaign that first captured this lead (Generate-Leads). Global
    # contact-once means a person stays with the FIRST campaign; a later
    # campaign's scrape that re-finds them is skipped, not reassigned. Nullable:
    # seed/manual/pre-S-5 leads have no campaign.
    campaign_id = Column(
        Integer, ForeignKey("campaigns.id"), nullable=True, index=True
    )

    # Deterministic global dedup key (li:/em:/nc: tier + sha256). Unique =>
    # contact-once: a second ingestion of the same identity can't create a row.
    dedup_key = Column(String(80), nullable=False, unique=True, index=True)

    stage = Column(String(24), nullable=False, server_default="new", default="new")

    bounced = Column(Boolean, nullable=False, server_default="0", default=False)
    unsubscribed = Column(Boolean, nullable=False, server_default="0", default=False)
    not_interested = Column(Boolean, nullable=False, server_default="0", default=False)

    source = Column(String(40), nullable=True)  # e.g. seed, apify, apollo
    archived = Column(Boolean, nullable=False, server_default="0", default=False)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    company = relationship("Company", back_populates="leads")
    events = relationship(
        "LeadEvent",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="LeadEvent.id",
    )


class LeadEvent(Base):
    __tablename__ = "lead_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    kind = Column(String(24), nullable=False)  # EVENT_KINDS
    from_value = Column(Text, nullable=True)
    to_value = Column(Text, nullable=True)

    # Actor snapshot — survives a later user rename/delete (auditable).
    actor_user_id = Column(Integer, nullable=True)
    actor_name = Column(String(160), nullable=True)

    created_at = Column(DateTime, default=func.now(), nullable=False)

    lead = relationship("Lead", back_populates="events")
