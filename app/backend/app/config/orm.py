"""SQLAlchemy ORM for the config feature.

Per OP #11, feature tables live here — never in `app/db/models.py`. Registered
on the shared `Base.metadata` via `app/db/__init__.py:init_db`.

One table holds all four catalog kinds (category | geography | role |
icp_filter) — `kind` discriminates. Soft-archive only (OP: no lost data);
nothing is ever hard-deleted.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.db.models import Base

# Allowed catalog kinds. Single source of truth — router + seed import this.
#   category         = mPower's own product categories (what mPower sells)
#   target_category  = target-customer product categories (what prospects make)
CATALOG_KINDS = ("category", "target_category", "geography", "role", "icp_filter")


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(32), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    value = Column(Text, nullable=True)  # free-text detail (e.g. ICP filter value)
    archived = Column(Boolean, nullable=False, server_default="0", default=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
