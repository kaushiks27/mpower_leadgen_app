"""Brain catalog ORM — mPower's own products + services (one master table).

Idempotent, never-lose-a-row design:
  * dedup_key (sha256 of a stable natural key) is UNIQUE — a re-sync upserts,
    never duplicates.
  * manual rows are protected: a sync never updates or deletes a row where
    manual = 1.
  * money kept as an exact decimal STRING (never float); the band is advisory.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.db.models import Base


class CatalogItem(Base):
    __tablename__ = "brain_catalog_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(16), nullable=False, index=True)          # product | service
    name = Column(String(300), nullable=False)
    handle = Column(String(200), nullable=True)                    # shopify handle / slug
    category = Column(String(120), nullable=True)
    price_inr = Column(String(32), nullable=True)                  # exact decimal string
    price_locked = Column(Boolean, nullable=False, server_default="0")  # manual price override survives sync
    # Advisory SalesPath data-confidence band (recorded + reversible, never load-bearing).
    band = Column(String(8), nullable=True)                        # Sure|Likely|Unsure|No
    band_reason = Column(Text, nullable=True)
    band_confidence = Column(String(8), nullable=True)             # decimal string 0..1
    band_input_hash = Column(String(64), nullable=True)            # skip re-verify if unchanged
    manual = Column(Boolean, nullable=False, server_default="0")   # protected from sync
    archived = Column(Boolean, nullable=False, server_default="0")
    source_url = Column(String(500), nullable=True)
    dedup_key = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
