"""Seed the Brain catalog from a bundled snapshot when the table is empty.

Prod uses ephemeral SQLite (KI-1) — the DB resets on every redeploy. This loads
the already-verified catalog (mPower's own products + services, WITH their
advisory SalesPath bands) on boot WITHOUT calling Apify or Claude, so **no
credits are spent** to re-populate prod after a redeploy.

Seeds ONLY when the table is empty — it never clobbers a real Sync or
manually-added rows. Each snapshot row carries its `band_input_hash`, so a later
Sync sees the content unchanged and SKIPS Claude re-verification (only the cheap
crawl runs, and only if the user chooses to Sync).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select

import app.db as db_mod
from app.brain.orm import CatalogItem

logger = logging.getLogger(__name__)

_SNAPSHOT = Path(__file__).parent / "seed_data" / "catalog_snapshot.json"


async def seed_brain_catalog_if_empty() -> None:
    """Load the snapshot into `brain_catalog_items` iff the table is empty."""
    if not _SNAPSHOT.exists():
        return
    async with db_mod.async_session() as db:
        count = await db.scalar(select(func.count()).select_from(CatalogItem))
        if count and count > 0:
            return  # real data present — never overwrite
        try:
            rows = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            logger.warning("brain: could not read catalog snapshot (%s)", e)
            return
        for r in rows:
            db.add(
                CatalogItem(
                    kind=r["kind"],
                    name=r["name"],
                    handle=r.get("handle"),
                    category=r.get("category"),
                    price_inr=r.get("price_inr"),
                    price_locked=bool(r.get("price_locked")),
                    band=r.get("band"),
                    band_reason=r.get("band_reason"),
                    band_confidence=r.get("band_confidence"),
                    band_input_hash=r.get("band_input_hash"),
                    manual=bool(r.get("manual")),
                    source_url=r.get("source_url"),
                    dedup_key=r["dedup_key"],
                )
            )
        await db.commit()
        logger.warning("brain: seeded %d catalog rows from snapshot", len(rows))
