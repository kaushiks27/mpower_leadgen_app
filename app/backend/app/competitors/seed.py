"""Seed the Competitors table from a bundled snapshot when empty.

Mirrors the Brain catalog seed: prod uses ephemeral SQLite (KI-1) that resets on
redeploy, so this re-loads an already-classified competitor snapshot on boot
WITHOUT spending Apify/Claude credits. Seeds ONLY when the table is empty — it
never clobbers a real Sync or manually-added rows. A no-op until a snapshot file
exists (the first live Sync produces one).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select

import app.db as db_mod
from app.competitors.orm import CompetitorItem

logger = logging.getLogger(__name__)

_SNAPSHOT = Path(__file__).parent / "seed_data" / "competitors_snapshot.json"


async def seed_competitors_if_empty() -> None:
    """Load the snapshot into `competitor_items` iff the table is empty."""
    if not _SNAPSHOT.exists():
        return
    async with db_mod.async_session() as db:
        count = await db.scalar(select(func.count()).select_from(CompetitorItem))
        if count and count > 0:
            return  # real data present — never overwrite
        try:
            rows = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            logger.warning("competitors: could not read snapshot (%s)", e)
            return
        for r in rows:
            db.add(
                CompetitorItem(
                    name=r["name"],
                    website=r.get("website"),
                    website_verified=r.get("website_verified"),
                    domain=r.get("domain"),
                    country=r.get("country"),
                    scope=r.get("scope") or "global",
                    category=r.get("category"),
                    selling_to=r.get("selling_to"),
                    selling_to_note=r.get("selling_to_note"),
                    band=r.get("band"),
                    band_reason=r.get("band_reason"),
                    band_confidence=r.get("band_confidence"),
                    band_input_hash=r.get("band_input_hash"),
                    locked_fields=r.get("locked_fields"),
                    manual=bool(r.get("manual")),
                    source_url=r.get("source_url"),
                    dedup_key=r["dedup_key"],
                )
            )
        await db.commit()
        logger.warning("competitors: seeded %d rows from snapshot", len(rows))
