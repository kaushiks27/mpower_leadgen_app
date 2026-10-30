"""Customers ORM — mPower's worldwide prospective-customer list (one master table).

A customer = a company mPower would SELL drone batteries TO:
  * OEM        — a drone MANUFACTURER (builds drones, buys packs).
  * Reseller / Distributor — of drone batteries / mPower's product categories.

Idempotent, never-lose-a-row design (mirrors the Competitors table):
  * dedup_key (sha256 of the company's domain) is UNIQUE — a re-sync upserts.
  * manual rows are protected; a sync never updates/deletes manual = 1.
  * per-field human overrides remembered in `locked_fields`.
  * the genuine-customer band (is-this-a-real-customer confidence) is advisory.
  * ctype (OEM | Reseller | Distributor) is the Type column — advisory, blank when
    evidence does not state it (never a guess).
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.db.models import Base


class CustomerItem(Base):
    __tablename__ = "customer_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(300), nullable=False)
    website = Column(String(500), nullable=True)
    # Stage-2 website resolve: NULL = not yet checked, 1 = canonical URL confirmed
    # reachable, 0 = could not confirm (kept the candidate URL, flagged in UI).
    website_verified = Column(Boolean, nullable=True)
    domain = Column(String(255), nullable=True, index=True)        # normalized identity
    country = Column(String(120), nullable=True)                   # Location column
    # S-MS1 multi-source: company contact (one phone + one verified email) + the lane
    # that discovered the row. Harvested native (free) at upsert; email gap-filled +
    # MillionVerifier-graded for eligible (Sure/Likely) rows. Manual edits lock them.
    phone = Column(String(64), nullable=True)
    email = Column(String(255), nullable=True)
    email_quality = Column(String(16), nullable=True)              # valid|catch_all|invalid|unknown
    discovery_source = Column(String(32), nullable=True)           # maps|linkedin|indiamart|…|google
    scope = Column(String(8), nullable=False, server_default="global")  # local | global
    # mPower product/service category this customer buys/sells in — value comes
    # from the live brain_catalog_items category set (exactly mPower's own cats).
    category = Column(String(160), nullable=True)
    # Customer type — the Type column. OEM | Reseller | Distributor (or NULL).
    ctype = Column(String(12), nullable=True)
    # Advisory genuine-customer band (recorded + reversible).
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
