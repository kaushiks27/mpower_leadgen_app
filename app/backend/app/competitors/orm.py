"""Competitors ORM — mPower's worldwide direct-competitor list (one master table).

Idempotent, never-lose-a-row design (mirrors the Brain catalog):
  * dedup_key (sha256 of a stable natural key — the competitor's domain) is
    UNIQUE — a re-sync upserts, never duplicates.
  * manual rows are protected: a sync never updates or deletes a row where
    manual = 1.
  * per-field human overrides are remembered in `locked_fields` so a later sync
    never clobbers a value the user hand-edited (generalises the catalog's
    single price-lock to every editable column).
  * the SalesPath band (is-this-a-true-competitor confidence) is advisory —
    recorded + reversible, never load-bearing.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.db.models import Base


class CompetitorItem(Base):
    __tablename__ = "competitor_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(300), nullable=False)
    website = Column(String(500), nullable=True)
    # Stage-2 website resolve: NULL = not yet checked, 1 = canonical URL confirmed
    # reachable, 0 = could not confirm (kept the candidate URL, flagged in UI).
    website_verified = Column(Boolean, nullable=True)
    domain = Column(String(255), nullable=True, index=True)        # normalized identity
    country = Column(String(120), nullable=True)
    # S-CR2 multi-source: which lane first discovered this row (provenance). The
    # per-source counts shown in the popup are ephemeral (job.detail); this is the
    # durable record. maps|linkedin|indiamart|thomasnet|europages|wlw|google.
    discovery_source = Column(String(32), nullable=True)
    scope = Column(String(8), nullable=False, server_default="global")  # local | global
    # mPower product/service category this competitor competes in — value comes
    # from the live brain_catalog_items category set (exactly mPower's own cats).
    category = Column(String(160), nullable=True)
    # Who they sell to (their customers): comma-joined names, best-effort.
    selling_to = Column(Text, nullable=True)
    selling_to_note = Column(Text, nullable=True)                  # e.g. "no public data found"
    # Advisory SalesPath true-competitor band (recorded + reversible).
    band = Column(String(8), nullable=True)                        # Sure|Likely|Unsure|No
    band_reason = Column(Text, nullable=True)
    band_confidence = Column(String(8), nullable=True)             # decimal string 0..1
    band_input_hash = Column(String(64), nullable=True)            # skip re-verify if unchanged
    # Comma-joined field names the user manually overrode (sync preserves them).
    locked_fields = Column(Text, nullable=True)
    manual = Column(Boolean, nullable=False, server_default="0")   # protected from sync
    archived = Column(Boolean, nullable=False, server_default="0")
    source_url = Column(String(500), nullable=True)                # where it was discovered
    dedup_key = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
