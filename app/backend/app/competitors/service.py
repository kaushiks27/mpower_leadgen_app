"""Competitors CRUD + idempotent upsert + classification application (DB I/O).

Deterministic core: dedup keys (sha256 of the competitor domain), idempotent
upsert, manual-row protection, per-field human-override locks, scope derivation.
No network here — the sync coroutine (`competitors.sync`) calls these after it
has discovered + classified competitors.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.competitors.models import CompetitorOut
from app.competitors.orm import CompetitorItem

BANDS = ("Sure", "Likely", "Unsure", "No")
_LOCAL_COUNTRIES = {"india", "in", "ind", "bharat"}


# --- normalization + keys (stable, deterministic) ---------------------------
def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _key(*parts: str) -> str:
    return hashlib.sha256("|".join(_norm(p) for p in parts).encode("utf-8")).hexdigest()


def _clean_str(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def normalize_domain(url_or_domain: str | None) -> str:
    """A stable lowercased registrable host (no scheme, no www, no path)."""
    if not url_or_domain:
        return ""
    raw = url_or_domain.strip()
    if "//" not in raw:
        raw = "//" + raw
    host = (urlparse(raw).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0].strip("/")


def dedup_key_synced(domain: str) -> str:
    """Key for a discovered competitor — its normalized domain is the identity."""
    return _key("competitor", normalize_domain(domain))


def dedup_key_manual(name: str) -> str:
    """Key for a manual competitor — salted so it never collides with a synced one."""
    return _key("competitor", _norm(name), "manual")


def content_hash(name: str, domain: str | None) -> str:
    """Re-classify key — the DOMAIN is the stable identity. Deliberately ignores
    `name`: the classifier itself corrects the name, so including it would make
    every re-sync re-classify (the name changed) and break idempotency. `name`
    is kept in the signature for call-site symmetry."""
    return _key(normalize_domain(domain))


def derive_scope(country: str | None) -> str:
    """Local = India; everything else = Global. Deterministic."""
    return "local" if _norm(country or "") in _LOCAL_COUNTRIES else "global"


def _locked_set(item: CompetitorItem) -> set[str]:
    return {f for f in (item.locked_fields or "").split(",") if f}


# --- read -------------------------------------------------------------------
def to_out(item: CompetitorItem) -> CompetitorOut:
    return CompetitorOut(
        id=item.id,
        name=item.name,
        website=item.website,
        website_verified=item.website_verified,
        domain=item.domain,
        country=item.country,
        discovery_source=item.discovery_source,
        scope=item.scope or "global",
        category=item.category,
        selling_to=item.selling_to,
        selling_to_note=item.selling_to_note,
        band=item.band,
        band_reason=item.band_reason,
        band_confidence=item.band_confidence,
        locked_fields=sorted(_locked_set(item)),
        manual=bool(item.manual),
        archived=bool(item.archived),
        source_url=item.source_url,
        created_at=item.created_at.isoformat() if item.created_at else "",
        updated_at=item.updated_at.isoformat() if item.updated_at else "",
    )


async def get_one(db: AsyncSession, item_id: int) -> CompetitorItem | None:
    return await db.get(CompetitorItem, item_id)


async def list_competitors(
    db: AsyncSession, *, scope: str | None = None, include_archived: bool = False
) -> list[CompetitorItem]:
    stmt = select(CompetitorItem)
    if scope is not None:
        stmt = stmt.where(CompetitorItem.scope == scope)
    if not include_archived:
        stmt = stmt.where(CompetitorItem.archived.is_(False))
    # Deterministic ordering: country then name (stable tiebreak on id).
    stmt = stmt.order_by(CompetitorItem.country, CompetitorItem.name, CompetitorItem.id)
    return list((await db.execute(stmt)).scalars().all())


async def summary(db: AsyncSession) -> dict:
    base = select(func.count()).select_from(CompetitorItem).where(
        CompetitorItem.archived.is_(False)
    )
    total = await db.scalar(base)
    local = await db.scalar(base.where(CompetitorItem.scope == "local"))
    glob = await db.scalar(base.where(CompetitorItem.scope == "global"))
    manual = await db.scalar(base.where(CompetitorItem.manual.is_(True)))
    banded = await db.scalar(base.where(CompetitorItem.band.isnot(None)))
    last = await db.scalar(select(func.max(CompetitorItem.updated_at)))
    return {
        "total": int(total or 0),
        "local": int(local or 0),
        "global_": int(glob or 0),
        "manual": int(manual or 0),
        "banded": int(banded or 0),
        "last_synced": last.isoformat() if last else None,
    }


async def mpower_categories(db: AsyncSession) -> list[str]:
    """The live Products & Services category set (a SQL read of the brain table —
    a DATA dependency, not a code import). Keeps the competitor Category column
    EXACTLY in sync with mPower's own catalog categories. Deterministic order.
    """
    try:
        rows = await db.execute(
            text(
                "SELECT DISTINCT category FROM brain_catalog_items "
                "WHERE archived = 0 AND category IS NOT NULL AND category != '' "
                "ORDER BY category"
            )
        )
    except Exception:  # noqa: BLE001 — table absent (fresh DB) → no categories yet
        return []
    cats = [r[0] for r in rows.fetchall() if r[0] and r[0] != "Manual"]
    return sorted(set(cats))


async def existing_domains(db: AsyncSession) -> set[str]:
    """Normalized domains already in the table (non-archived). A fresh Sync pre-seeds
    discovery's `seen` set with these so a REPEAT run surfaces NEW competitors (the next
    N per source) instead of re-discovering the same top hits. Deterministic set."""
    rows = await db.execute(
        select(CompetitorItem.domain).where(
            CompetitorItem.archived.is_(False), CompetitorItem.domain.isnot(None)
        )
    )
    return {normalize_domain(d) for (d,) in rows.all() if d and normalize_domain(d)}


# --- write ------------------------------------------------------------------
async def add_manual(
    db: AsyncSession,
    *,
    name: str,
    website: str | None,
    country: str | None,
    category: str | None,
    selling_to: str | None,
) -> CompetitorItem:
    """Add a human-authoritative competitor. Band 'Sure', protected from sync,
    every provided field locked so a later sync never overwrites it.

    Keyed by DOMAIN when a website is given (so a later discovery of the same
    company collides → is skipped, never duplicated); name-salted otherwise.
    """
    dom = normalize_domain(website)
    key = dedup_key_synced(dom) if dom else dedup_key_manual(name)
    existing = (
        await db.execute(select(CompetitorItem).where(CompetitorItem.dedup_key == key))
    ).scalars().first()
    if existing is not None and not existing.archived:
        raise ValueError("that competitor already exists")
    _provided = {
        "name": name, "website": website, "country": country,
        "category": category, "selling_to": selling_to,
    }
    locked = ",".join(f for f, v in _provided.items() if v)
    if existing is not None:  # was archived — restore + refresh
        existing.archived = False
        existing.name = name
        existing.website = website
        existing.domain = normalize_domain(website)
        existing.country = country
        existing.scope = derive_scope(country)
        existing.category = category
        existing.selling_to = selling_to
        existing.band = "Sure"
        existing.band_reason = "Manually added (human-authoritative)"
        existing.band_confidence = "1.0"
        existing.locked_fields = locked
        await db.commit()
        await db.refresh(existing)
        return existing
    item = CompetitorItem(
        name=name,
        website=website,
        domain=normalize_domain(website),
        country=country,
        scope=derive_scope(country),
        category=category,
        selling_to=selling_to,
        selling_to_note=None,
        band="Sure",
        band_reason="Manually added (human-authoritative)",
        band_confidence="1.0",
        locked_fields=locked,
        manual=True,
        archived=False,
        source_url=None,
        dedup_key=key,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def edit_competitor(
    db: AsyncSession,
    item_id: int,
    *,
    name: str | None = None,
    website: str | None = None,
    country: str | None = None,
    category: str | None = None,
    selling_to: str | None = None,
    archived: bool | None = None,
) -> CompetitorItem | None:
    """Inline-edit a competitor. Each edited field is LOCKED so a later sync never
    clobbers the human value (generalises the catalog price-lock to every column)."""
    item = await db.get(CompetitorItem, item_id)
    if item is None:
        return None
    locked = _locked_set(item)
    if name is not None:
        item.name = name
        locked.add("name")
    if website is not None:
        item.website = website
        item.domain = normalize_domain(website)
        locked.add("website")
    if country is not None:
        item.country = country
        item.scope = derive_scope(country)
        locked.add("country")
    if category is not None:
        item.category = category
        locked.add("category")
    if selling_to is not None:
        item.selling_to = selling_to
        locked.add("selling_to")
    if archived is not None:
        item.archived = archived
    item.locked_fields = ",".join(sorted(locked))
    await db.commit()
    await db.refresh(item)
    return item


async def upsert_discovered(db: AsyncSession, rows: list[dict]) -> tuple[int, int, int]:
    """Idempotently upsert discovered competitors. Returns (inserted, updated, skipped_manual).

    Each row dict: name, website, domain, country, category, source_url.
    Classification fields are filled later by apply_classification. A row whose
    dedup_key matches a manual row is SKIPPED. Locked fields are never overwritten.
    """
    inserted = updated = skipped_manual = 0
    for r in rows:
        dom = normalize_domain(r.get("domain") or r.get("website") or "")
        if not dom:
            continue  # no stable identity — skip (deterministic)
        key = dedup_key_synced(dom)
        existing = (
            await db.execute(select(CompetitorItem).where(CompetitorItem.dedup_key == key))
        ).scalars().first()
        if existing is not None and existing.manual:
            skipped_manual += 1
            continue
        if existing is None:
            db.add(CompetitorItem(
                name=r.get("name") or dom,
                website=r.get("website"),
                domain=dom,
                country=_clean_str(r.get("country")),
                discovery_source=_clean_str(r.get("discovery_source")),
                scope=derive_scope(r.get("country")),
                category=r.get("category"),
                source_url=r.get("source_url"),
                manual=False,
                archived=False,
                dedup_key=key,
            ))
            inserted += 1
        else:
            locked = _locked_set(existing)
            if "name" not in locked and r.get("name"):
                existing.name = r["name"]
            if "website" not in locked and r.get("website"):
                existing.website = r["website"]
                existing.domain = dom
            if not existing.discovery_source and _clean_str(r.get("discovery_source")):
                existing.discovery_source = _clean_str(r.get("discovery_source"))
            existing.source_url = r.get("source_url") or existing.source_url
            existing.archived = False
            updated += 1
    await db.commit()
    return inserted, updated, skipped_manual


async def competitors_to_classify(db: AsyncSession) -> list[CompetitorItem]:
    """Non-manual rows whose band is missing or whose identity changed since banding."""
    rows = list(
        (await db.execute(
            select(CompetitorItem).where(
                CompetitorItem.manual.is_(False), CompetitorItem.archived.is_(False)
            )
        )).scalars().all()
    )
    out = []
    for it in rows:
        h = content_hash(it.name, it.domain)
        if it.band is None or it.band_input_hash != h:
            out.append(it)
    return out


async def competitors_for_sync(db: AsyncSession) -> list[CompetitorItem]:
    """EVERY non-manual, non-archived competitor — the full re-enrich set.

    The category-first pipeline re-runs website-resolve + crawl-enrich + classify
    over all existing rows in place (user choice: "keep, re-enrich in place"),
    refreshing columns and respecting per-field human locks. Deterministic order
    (domain then id) so progress is stable across a pause/resume."""
    rows = list(
        (await db.execute(
            select(CompetitorItem)
            .where(CompetitorItem.manual.is_(False), CompetitorItem.archived.is_(False))
            .order_by(CompetitorItem.domain, CompetitorItem.id)
        )).scalars().all()
    )
    return rows


async def apply_classification(
    db: AsyncSession,
    item_id: int,
    *,
    band: str,
    reason: str,
    confidence: str,
    input_hash: str,
    name: str | None = None,
    country: str | None = None,
    category: str | None = None,
    selling_to: str | None = None,
    selling_to_note: str | None = None,
) -> None:
    """Write one Claude classification verdict. Band clamped to the valid enum;
    locked (human-edited) fields are never overwritten."""
    item = await db.get(CompetitorItem, item_id)
    if item is None:
        return
    locked = _locked_set(item)
    item.band = band if band in BANDS else "Unsure"
    item.band_reason = reason
    item.band_confidence = confidence
    item.band_input_hash = input_hash
    if "name" not in locked and name:
        item.name = name
    if "country" not in locked and country:
        item.country = country
        item.scope = derive_scope(country)
    if "category" not in locked and category:
        item.category = category
    if "selling_to" not in locked:
        if selling_to:
            item.selling_to = selling_to
            item.selling_to_note = None
        else:
            item.selling_to_note = selling_to_note or item.selling_to_note
    await db.commit()


# --- category-first pipeline: granular per-stage writers --------------------
# Each stage writes only its own column(s) so the modal can show columns filling
# step-by-step. All are locked-aware (human edits survive a sync) + idempotent.

async def set_website(
    db: AsyncSession, item_id: int, *, website: str, domain: str, verified: bool
) -> None:
    """Stage 2: persist the resolved canonical website + reachability flag. Skips
    the value when the user has locked `website` (but still records the flag)."""
    item = await db.get(CompetitorItem, item_id)
    if item is None:
        return
    if "website" not in _locked_set(item):
        item.website = website
        item.domain = domain or item.domain
    item.website_verified = verified
    await db.commit()


async def apply_enrichment(
    db: AsyncSession,
    item_id: int,
    *,
    name: str | None = None,
    country: str | None = None,
    category: str | None = None,
    selling_to: str | None = None,
    selling_to_note: str | None = None,
    write_country: bool = False,
    write_selling_to: bool = False,
) -> None:
    """Stages 3+4: write the EXTRACT-pass fields. `write_country` / `write_selling_to`
    gate which column this call commits (so stage 3 fills Country, stage 4 fills
    Selling-to, from the one cached extraction). Category is filled ONLY when the
    row is still blank — the originating-search category always wins. Locked human
    fields are never overwritten."""
    item = await db.get(CompetitorItem, item_id)
    if item is None:
        return
    locked = _locked_set(item)
    if name and "name" not in locked and not item.manual:
        item.name = name
    # Category: originating-search value is authoritative — only fill a gap.
    if category and "category" not in locked and not item.category:
        item.category = category
    if write_country and "country" not in locked and country:
        item.country = country
        item.scope = derive_scope(country)
    if write_selling_to and "selling_to" not in locked:
        if selling_to:
            item.selling_to = selling_to
            item.selling_to_note = None
        else:
            item.selling_to_note = selling_to_note or item.selling_to_note
    await db.commit()


async def apply_band(
    db: AsyncSession,
    item_id: int,
    *,
    band: str,
    reason: str,
    confidence: str,
    input_hash: str,
    name: str | None = None,
) -> None:
    """Stage 5: write ONLY the true-competitor band (+ reason/confidence/hash).
    Never touches country/category/selling-to (filled in stages 3+4). Band clamped
    to the valid enum (never silently 'Sure'); name corrected only if not locked."""
    item = await db.get(CompetitorItem, item_id)
    if item is None:
        return
    item.band = band if band in BANDS else "Unsure"
    item.band_reason = reason
    item.band_confidence = confidence
    item.band_input_hash = input_hash
    if name and "name" not in _locked_set(item) and not item.manual:
        item.name = name
    await db.commit()
