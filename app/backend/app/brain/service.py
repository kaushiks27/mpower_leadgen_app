"""Brain catalog CRUD + idempotent upsert + band application (pure DB I/O).

Deterministic core: dedup keys (sha256), idempotent upsert, manual-row
protection, exact-decimal prices. No network here — the sync coroutine
(`brain.sync`) calls these after it has fetched data.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.models import CatalogItemOut
from app.brain.orm import CatalogItem

BANDS = ("Sure", "Likely", "Unsure", "No")


# --- dedup keys (stable, deterministic) -------------------------------------
def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _key(*parts: str) -> str:
    return hashlib.sha256("|".join(_norm(p) for p in parts).encode("utf-8")).hexdigest()


def dedup_key_synced(kind: str, handle: str) -> str:
    """Key for a sync-sourced row: kind + stable handle/slug."""
    return _key(kind, handle)


def dedup_key_manual(kind: str, name: str) -> str:
    """Key for a manual row — salted so it never collides with a synced handle."""
    return _key(kind, name, "manual")


def content_hash(name: str, price: str | None, category: str | None, has_evidence: bool) -> str:
    """Hash of the fields the verifier reads — re-verify only when this changes."""
    return _key(name, price or "", category or "", "ev" if has_evidence else "no")


# --- read -------------------------------------------------------------------
def to_out(item: CatalogItem) -> CatalogItemOut:
    return CatalogItemOut(
        id=item.id,
        kind=item.kind,
        name=item.name,
        handle=item.handle,
        category=item.category,
        price_inr=item.price_inr,
        price_locked=bool(item.price_locked),
        band=item.band,
        band_reason=item.band_reason,
        band_confidence=item.band_confidence,
        manual=bool(item.manual),
        archived=bool(item.archived),
        source_url=item.source_url,
        created_at=item.created_at.isoformat() if item.created_at else "",
        updated_at=item.updated_at.isoformat() if item.updated_at else "",
    )


async def list_items(
    db: AsyncSession, *, kind: str | None = None, include_archived: bool = False
) -> list[CatalogItem]:
    stmt = select(CatalogItem)
    if kind is not None:
        stmt = stmt.where(CatalogItem.kind == kind)
    if not include_archived:
        stmt = stmt.where(CatalogItem.archived.is_(False))
    # Deterministic ordering: manual first, then band priority, then name.
    stmt = stmt.order_by(CatalogItem.kind, CatalogItem.name)
    return list((await db.execute(stmt)).scalars().all())


async def summary(db: AsyncSession) -> dict:
    prod = await db.scalar(
        select(func.count()).select_from(CatalogItem).where(
            CatalogItem.kind == "product", CatalogItem.archived.is_(False)
        )
    )
    svc = await db.scalar(
        select(func.count()).select_from(CatalogItem).where(
            CatalogItem.kind == "service", CatalogItem.archived.is_(False)
        )
    )
    manual = await db.scalar(
        select(func.count()).select_from(CatalogItem).where(
            CatalogItem.manual.is_(True), CatalogItem.archived.is_(False)
        )
    )
    banded = await db.scalar(
        select(func.count()).select_from(CatalogItem).where(
            CatalogItem.band.isnot(None), CatalogItem.archived.is_(False)
        )
    )
    last = await db.scalar(select(func.max(CatalogItem.updated_at)))
    return {
        "products": int(prod or 0),
        "services": int(svc or 0),
        "manual": int(manual or 0),
        "banded": int(banded or 0),
        "last_synced": last.isoformat() if last else None,
    }


# --- write ------------------------------------------------------------------
async def add_manual(
    db: AsyncSession, *, kind: str, name: str, price_inr: str | None
) -> CatalogItem:
    """Add a human-authoritative row. Manual rows are band 'Sure' and protected.

    Raises ValueError if an identical manual row already exists (un-archived).
    """
    key = dedup_key_manual(kind, name)
    existing = (
        await db.execute(select(CatalogItem).where(CatalogItem.dedup_key == key))
    ).scalars().first()
    if existing is not None and not existing.archived:
        raise ValueError("that item already exists")
    if existing is not None:  # was archived — restore + refresh
        existing.archived = False
        existing.name = name
        existing.price_inr = price_inr
        existing.band = "Sure"
        existing.band_reason = "Manually added (human-authoritative)"
        existing.band_confidence = "1.0"
        await db.commit()
        await db.refresh(existing)
        return existing
    item = CatalogItem(
        kind=kind,
        name=name,
        handle=None,
        category="Manual",
        price_inr=price_inr,
        band="Sure",
        band_reason="Manually added (human-authoritative)",
        band_confidence="1.0",
        manual=True,
        archived=False,
        source_url=None,
        dedup_key=key,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def edit_item(
    db: AsyncSession,
    item_id: int,
    *,
    name: str | None = None,
    price_inr: str | None = None,
    archived: bool | None = None,
) -> CatalogItem | None:
    item = await db.get(CatalogItem, item_id)
    if item is None:
        return None
    if name is not None:
        item.name = name
    if price_inr is not None:
        # A manual price override is locked so a later sync never clobbers it.
        item.price_inr = price_inr
        item.price_locked = True
    if archived is not None:
        item.archived = archived
    await db.commit()
    await db.refresh(item)
    return item


async def upsert_synced(db: AsyncSession, rows: list[dict]) -> tuple[int, int, int]:
    """Idempotently upsert sync-sourced rows. Returns (inserted, updated, skipped_manual).

    Each row dict: kind, name, handle, category, price_inr, source_url.
    A row whose dedup_key matches a manual row is SKIPPED (manual is protected).
    """
    inserted = updated = skipped_manual = 0
    for r in rows:
        key = dedup_key_synced(r["kind"], r.get("handle") or r["name"])
        existing = (
            await db.execute(select(CatalogItem).where(CatalogItem.dedup_key == key))
        ).scalars().first()
        if existing is not None and existing.manual:
            skipped_manual += 1
            continue
        if existing is None:
            db.add(CatalogItem(
                kind=r["kind"], name=r["name"], handle=r.get("handle"),
                category=r.get("category"), price_inr=r.get("price_inr"),
                source_url=r.get("source_url"), manual=False, archived=False,
                dedup_key=key,
            ))
            inserted += 1
        else:
            existing.name = r["name"]
            existing.category = r.get("category")
            if not existing.price_locked:  # a manual price override is preserved
                existing.price_inr = r.get("price_inr")
            existing.source_url = r.get("source_url")
            existing.archived = False
            updated += 1
    await db.commit()
    return inserted, updated, skipped_manual


async def items_to_verify(
    db: AsyncSession, evidence_by_id: dict[int, str]
) -> list[CatalogItem]:
    """Non-manual rows whose band is missing or whose content changed since banding."""
    rows = list(
        (await db.execute(
            select(CatalogItem).where(
                CatalogItem.manual.is_(False), CatalogItem.archived.is_(False)
            )
        )).scalars().all()
    )
    out = []
    for it in rows:
        h = content_hash(it.name, it.price_inr, it.category, bool(evidence_by_id.get(it.id)))
        if it.band is None or it.band_input_hash != h:
            out.append(it)
    return out


async def apply_band(
    db: AsyncSession,
    item_id: int,
    *,
    band: str,
    reason: str,
    confidence: str,
    input_hash: str,
) -> None:
    """Write one verifier verdict. Band is clamped to the valid enum."""
    item = await db.get(CatalogItem, item_id)
    if item is None:
        return
    item.band = band if band in BANDS else "Unsure"
    item.band_reason = reason
    item.band_confidence = confidence
    item.band_input_hash = input_hash
    await db.commit()
