"""Idempotent catalog seed from the locked interview decisions.

Seeds geographies (India + Global), the four target-role buckets (Q6), and the
three ICP segments (Q4) on first boot. Product categories are intentionally NOT
seeded — admin adds mPower's product categories themselves.

Runs once-effectively: per-kind, if any row of that kind already exists we skip
that kind (so admin edits/archives are never clobbered on reboot). Runs from
FastAPI lifespan after init_db.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.config.orm import CatalogItem

logger = logging.getLogger(__name__)

# (kind, name, value) — locked decisions (slicing_plan §Locked Defaults 3/4/6).
SEED_ITEMS: tuple[tuple[str, str, str | None], ...] = (
    ("geography", "India", None),
    ("geography", "Global", None),
    ("role", "Procurement / Sourcing / Supply-chain", None),
    ("role", "Founder / CEO / CXO / Owner", None),
    ("role", "R&D / Engineering / Product / Hardware", None),
    ("role", "Operations / Fleet / Maintenance", None),
    # S-5d: `value` holds the drone-anchored Apify `company_keywords` for this
    # segment (comma-separated, OR-matched), decoupled from the display name so
    # the search stays strictly drone-related. Editable per campaign-team needs.
    ("icp_filter", "Drone OEMs / Manufacturers", "drone manufacturer, drone OEM, UAV manufacturer"),
    ("icp_filter", "Agri-drone Operators / RPTOs", "drone operator, drone fleet operator, agri drone"),
    ("icp_filter", "Distributors / Resellers", "drone distributor, drone reseller, drone dealer"),
)

# S-5d backfill: ICP filters seeded before the `value` carried real keywords
# stored the placeholder "ICP segment". Map name -> drone keywords so a
# persistent DB self-heals on boot (idempotent; only touches placeholder rows).
ICP_KEYWORD_BACKFILL: dict[str, str] = {
    "Drone OEMs / Manufacturers": "drone manufacturer, drone OEM, UAV manufacturer",
    "Agri-drone Operators / RPTOs": "drone operator, drone fleet operator, agri drone",
    "Distributors / Resellers": "drone distributor, drone reseller, drone dealer",
}


async def _backfill_icp_keywords(db) -> int:
    """Set drone keywords on ICP filters still holding the old placeholder.

    Idempotent + non-destructive: only rewrites rows whose value is NULL or the
    legacy "ICP segment" placeholder, and never touches a value an admin has
    customised. Runs on every boot so a persistent DB self-heals (S-5d).
    """
    updated = 0
    rows = (
        await db.execute(
            select(CatalogItem).where(CatalogItem.kind == "icp_filter")
        )
    ).scalars().all()
    for item in rows:
        kw = ICP_KEYWORD_BACKFILL.get(item.name)
        if kw and (item.value is None or item.value.strip() in ("", "ICP segment")):
            item.value = kw
            updated += 1
    return updated


async def seed_catalog_if_missing() -> None:
    import app.db as db_mod  # re-import so test fixtures swapping the engine win

    seeded_kinds = {kind for kind, _, _ in SEED_ITEMS}

    async with db_mod.async_session() as db:
        # Which kinds already have rows? Skip those — never clobber admin edits.
        existing = {
            row[0]
            for row in (
                await db.execute(
                    select(CatalogItem.kind).group_by(CatalogItem.kind)
                )
            ).all()
        }
        to_seed = [
            (kind, name, value)
            for (kind, name, value) in SEED_ITEMS
            if kind in seeded_kinds and kind not in existing
        ]
        for kind, name, value in to_seed:
            db.add(CatalogItem(kind=kind, name=name, value=value))
        # Always run the ICP keyword backfill — fresh inserts already carry the
        # right value; pre-S-5d rows on a persistent DB get healed here.
        healed = await _backfill_icp_keywords(db)
        if not to_seed and not healed:
            return
        await db.commit()
        logger.info(
            "seed_catalog: inserted %d, backfilled %d ICP keywords",
            len(to_seed), healed,
        )
