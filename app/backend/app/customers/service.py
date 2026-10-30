"""Customers CRUD + idempotent upsert + classification application (DB I/O).

Deterministic core: dedup keys (sha256 of the company domain), idempotent upsert,
manual-row protection, per-field human-override locks, scope derivation. No network
here — the sync coroutine (`customers.sync`) calls these after it has discovered +
classified customers.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.customers.models import CustomerOut
from app.customers.orm import CustomerItem

BANDS = ("Sure", "Likely", "Unsure", "No")
CTYPES = ("OEM", "Reseller", "Distributor")
_LOCAL_COUNTRIES = {"india", "in", "ind", "bharat"}


# --- normalization + keys (stable, deterministic) ---------------------------
def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _key(*parts: str) -> str:
    return hashlib.sha256("|".join(_norm(p) for p in parts).encode("utf-8")).hexdigest()


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
    """Key for a discovered customer — its normalized domain is the identity."""
    return _key("customer", normalize_domain(domain))


def dedup_key_manual(name: str) -> str:
    """Key for a manual customer — salted so it never collides with a synced one."""
    return _key("customer", _norm(name), "manual")


def content_hash(name: str, domain: str | None) -> str:
    """Re-classify key — the DOMAIN is the stable identity (ignores `name`, which the
    classifier itself corrects). `name` kept for call-site symmetry."""
    return _key(normalize_domain(domain))


def derive_scope(country: str | None) -> str:
    """Local = India; everything else = Global. Deterministic."""
    return "local" if _norm(country or "") in _LOCAL_COUNTRIES else "global"


def _clamp_ctype(ctype: str | None) -> str | None:
    return ctype if ctype in CTYPES else None


def _locked_set(item: CustomerItem) -> set[str]:
    return {f for f in (item.locked_fields or "").split(",") if f}


# --- read -------------------------------------------------------------------
def to_out(item: CustomerItem) -> CustomerOut:
    return CustomerOut(
        id=item.id,
        name=item.name,
        website=item.website,
        website_verified=item.website_verified,
        domain=item.domain,
        country=item.country,
        phone=item.phone,
        email=item.email,
        email_quality=item.email_quality,
        discovery_source=item.discovery_source,
        scope=item.scope or "global",
        category=item.category,
        ctype=item.ctype,
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


async def get_one(db: AsyncSession, item_id: int) -> CustomerItem | None:
    return await db.get(CustomerItem, item_id)


async def list_customers(
    db: AsyncSession, *, scope: str | None = None, include_archived: bool = False
) -> list[CustomerItem]:
    stmt = select(CustomerItem)
    if scope is not None:
        stmt = stmt.where(CustomerItem.scope == scope)
    if not include_archived:
        stmt = stmt.where(CustomerItem.archived.is_(False))
    # Deterministic ordering: country then name (stable tiebreak on id).
    stmt = stmt.order_by(CustomerItem.country, CustomerItem.name, CustomerItem.id)
    return list((await db.execute(stmt)).scalars().all())


async def summary(db: AsyncSession) -> dict:
    base = select(func.count()).select_from(CustomerItem).where(
        CustomerItem.archived.is_(False)
    )
    total = await db.scalar(base)
    local = await db.scalar(base.where(CustomerItem.scope == "local"))
    glob = await db.scalar(base.where(CustomerItem.scope == "global"))
    manual = await db.scalar(base.where(CustomerItem.manual.is_(True)))
    banded = await db.scalar(base.where(CustomerItem.band.isnot(None)))
    last = await db.scalar(select(func.max(CustomerItem.updated_at)))
    return {
        "total": int(total or 0),
        "local": int(local or 0),
        "global_": int(glob or 0),
        "manual": int(manual or 0),
        "banded": int(banded or 0),
        "last_synced": last.isoformat() if last else None,
    }


async def mpower_categories(db: AsyncSession) -> list[str]:
    """The live Products & Services category set (a SQL read of the brain table — a
    DATA dependency, not a code import). Keeps the customer Category column EXACTLY
    in sync with mPower's own catalog categories. Deterministic order."""
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


# --- write ------------------------------------------------------------------
async def add_manual(
    db: AsyncSession,
    *,
    name: str,
    website: str | None,
    country: str | None,
    category: str | None,
    ctype: str | None,
) -> CustomerItem:
    """Add a human-authoritative customer. Band 'Sure', protected from sync, every
    provided field locked so a later sync never overwrites it. Keyed by DOMAIN when a
    website is given; name-salted otherwise."""
    dom = normalize_domain(website)
    key = dedup_key_synced(dom) if dom else dedup_key_manual(name)
    ctype = _clamp_ctype(ctype)
    existing = (
        await db.execute(select(CustomerItem).where(CustomerItem.dedup_key == key))
    ).scalars().first()
    if existing is not None and not existing.archived:
        raise ValueError("that customer already exists")
    _provided = {
        "name": name, "website": website, "country": country,
        "category": category, "ctype": ctype,
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
        existing.ctype = ctype
        existing.band = "Sure"
        existing.band_reason = "Manually added (human-authoritative)"
        existing.band_confidence = "1.0"
        existing.locked_fields = locked
        await db.commit()
        await db.refresh(existing)
        return existing
    item = CustomerItem(
        name=name,
        website=website,
        domain=normalize_domain(website),
        country=country,
        scope=derive_scope(country),
        category=category,
        ctype=ctype,
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


async def edit_customer(
    db: AsyncSession,
    item_id: int,
    *,
    name: str | None = None,
    website: str | None = None,
    country: str | None = None,
    category: str | None = None,
    ctype: str | None = None,
    archived: bool | None = None,
) -> CustomerItem | None:
    """Inline-edit a customer. Each edited field is LOCKED so a later sync never
    clobbers the human value."""
    item = await db.get(CustomerItem, item_id)
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
    if ctype is not None:
        item.ctype = _clamp_ctype(ctype)
        locked.add("ctype")
    if archived is not None:
        item.archived = archived
    item.locked_fields = ",".join(sorted(locked))
    await db.commit()
    await db.refresh(item)
    return item


async def upsert_discovered(db: AsyncSession, rows: list[dict]) -> tuple[int, int, int]:
    """Idempotently upsert discovered customers. Returns (inserted, updated, skipped_manual).

    Each row dict: name, website, domain, country, category, ctype, source_url. A row
    whose dedup_key matches a manual row is SKIPPED. Locked fields never overwritten."""
    inserted = updated = skipped_manual = 0
    for r in rows:
        dom = normalize_domain(r.get("domain") or r.get("website") or "")
        if not dom:
            continue  # no stable identity — skip (deterministic)
        key = dedup_key_synced(dom)
        existing = (
            await db.execute(select(CustomerItem).where(CustomerItem.dedup_key == key))
        ).scalars().first()
        if existing is not None and existing.manual:
            skipped_manual += 1
            continue
        if existing is None:
            db.add(CustomerItem(
                name=r.get("name") or dom,
                website=r.get("website"),
                domain=dom,
                country=r.get("country"),
                phone=_clean_str(r.get("phone")),
                email=_clean_email(r.get("email")),
                discovery_source=_clean_str(r.get("discovery_source")),
                scope=derive_scope(r.get("country")),
                category=r.get("category"),
                ctype=_clamp_ctype(r.get("ctype")),
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
            # Native-harvested contact: fill blanks only (Stage 6 + manual edits win).
            if "phone" not in locked and not existing.phone and _clean_str(r.get("phone")):
                existing.phone = _clean_str(r.get("phone"))
            if "email" not in locked and not existing.email and _clean_email(r.get("email")):
                existing.email = _clean_email(r.get("email"))
            if not existing.discovery_source and r.get("discovery_source"):
                existing.discovery_source = _clean_str(r.get("discovery_source"))
            existing.source_url = r.get("source_url") or existing.source_url
            existing.archived = False
            updated += 1
    await db.commit()
    return inserted, updated, skipped_manual


def _clean_str(v) -> str | None:
    s = str(v).strip() if v else ""
    return s or None


def _clean_email(v) -> str | None:
    s = str(v).strip().lower() if v else ""
    return s if s and "@" in s else None


async def customers_to_enrich(db: AsyncSession, *, limit: int | None = None) -> list[CustomerItem]:
    """Stage-6 target set: eligible (Sure/Likely) non-manual, non-archived customers WITH
    a domain, missing a phone OR an email, that have NEVER been enriched (email_quality
    IS NULL — the attempt stamps it, so a row is tried at most once and never re-spends
    credits). Deterministic order (domain, id); capped to `limit` so each Sync does the
    next batch. Manual rows are excluded (their contacts are human-authoritative)."""
    rows = list(
        (await db.execute(
            select(CustomerItem)
            .where(
                CustomerItem.manual.is_(False),
                CustomerItem.archived.is_(False),
                CustomerItem.band.in_(("Sure", "Likely")),
                CustomerItem.domain.isnot(None),
                CustomerItem.domain != "",
                CustomerItem.email_quality.is_(None),  # not yet attempted
            )
            .order_by(CustomerItem.domain, CustomerItem.id)
        )).scalars().all()
    )
    out = [it for it in rows if not it.phone or not it.email]
    return out[:limit] if limit else out


async def set_contact(
    db: AsyncSession,
    item_id: int,
    *,
    phone: str | None,
    email: str | None,
    email_quality: str | None,
) -> None:
    """Stage-6 contact writer with deterministic precedence (RP3).

    phone  = Apollo (better source) overwrites unless the field is locked; a blank
             Apollo result keeps the native-scraped phone (never lose a contact).
    email  = an Apollo+MillionVerifier valid/catch_all email is written (overwrites an
             unverified native value); an invalid/unknown verdict NEVER lands an email —
             only the quality flag is recorded. Locked human edits always win."""
    item = await db.get(CustomerItem, item_id)
    if item is None:
        return
    locked = _locked_set(item)
    ph = _clean_str(phone)
    if ph and "phone" not in locked:
        item.phone = ph
    em = _clean_email(email)
    if em and email_quality in ("valid", "catch_all") and "email" not in locked:
        item.email = em
        item.email_quality = email_quality
    elif email_quality and item.email_quality is None:
        # Attempted but no deliverable email — stamp the verdict (never a bad address)
        # so this row is marked enriched and never re-tried / re-charged.
        item.email_quality = email_quality
    await db.commit()


async def customers_to_classify(db: AsyncSession) -> list[CustomerItem]:
    """Non-manual rows whose band is missing or whose identity changed since banding.

    This is ALSO the RESUME row-set: a paused sync left these unfinished, so a resume
    re-runs stages 2→5 over exactly them (already-classified rows are skipped).
    Deterministic order (domain then id) so progress is stable across pause/resume."""
    rows = list(
        (await db.execute(
            select(CustomerItem)
            .where(CustomerItem.manual.is_(False), CustomerItem.archived.is_(False))
            .order_by(CustomerItem.domain, CustomerItem.id)
        )).scalars().all()
    )
    out = []
    for it in rows:
        h = content_hash(it.name, it.domain)
        if it.band is None or it.band_input_hash != h:
            out.append(it)
    return out


async def existing_domains(db: AsyncSession) -> set[str]:
    """Normalized domains already in the table (non-archived). A fresh Sync pre-seeds
    discovery's `seen` set with these so a REPEAT run surfaces NEW companies (the next
    N per source) instead of re-discovering the same top hits. Deterministic set."""
    rows = await db.execute(
        select(CustomerItem.domain).where(
            CustomerItem.archived.is_(False), CustomerItem.domain.isnot(None)
        )
    )
    return {normalize_domain(d) for (d,) in rows.all() if d and normalize_domain(d)}


async def customers_for_sync(db: AsyncSession) -> list[CustomerItem]:
    """EVERY non-manual, non-archived customer — the full re-enrich set (deterministic
    order). Used by a fresh Sync; Resume uses `customers_to_classify` (unfinished only)."""
    rows = list(
        (await db.execute(
            select(CustomerItem)
            .where(CustomerItem.manual.is_(False), CustomerItem.archived.is_(False))
            .order_by(CustomerItem.domain, CustomerItem.id)
        )).scalars().all()
    )
    return rows


# --- category-first pipeline: granular per-stage writers --------------------
async def set_website(
    db: AsyncSession, item_id: int, *, website: str, domain: str, verified: bool
) -> None:
    """Stage 2: persist the resolved canonical website + reachability flag. Skips the
    value when the user has locked `website` (but still records the flag)."""
    item = await db.get(CustomerItem, item_id)
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
    ctype: str | None = None,
    write_country: bool = False,
    write_ctype: bool = False,
) -> None:
    """Stages 3+4: write the EXTRACT-pass fields. `write_country` / `write_ctype` gate
    which column this call commits (stage 3 fills Country, stage 4 fills Type, from the
    one cached extraction). Category is filled ONLY when the row is still blank — the
    originating-search category always wins. Locked human fields never overwritten."""
    item = await db.get(CustomerItem, item_id)
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
    if write_ctype and "ctype" not in locked and ctype:
        item.ctype = _clamp_ctype(ctype)
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
    ctype: str | None = None,
) -> None:
    """Stage 5: write the genuine-customer band (+ reason/confidence/hash). Band clamped
    to the valid enum (never silently 'Sure'). The strong model may also correct the
    Type — applied only when the model is confident AND the field is not locked/blank-safe."""
    item = await db.get(CustomerItem, item_id)
    if item is None:
        return
    locked = _locked_set(item)
    item.band = band if band in BANDS else "Unsure"
    item.band_reason = reason
    item.band_confidence = confidence
    item.band_input_hash = input_hash
    if name and "name" not in locked and not item.manual:
        item.name = name
    # The band model sees the full enriched line — let it fill a still-blank Type.
    if ctype and "ctype" not in locked and not item.ctype:
        item.ctype = _clamp_ctype(ctype)
    await db.commit()
