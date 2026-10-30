"""Assemble the canonical Generate-Leads filter lists from the DB (async I/O).

Reads are one-way to infra + reused tables only (OP #11): the Customers brain
(`customer_items`) for the pickable companies + countries, the brain catalog
distinct-categories (the SAME SQL the Customers categories endpoint uses — a DATA
dependency, not a code import), config for the static type list, and the static
role taxonomy. All ordering is deterministic so the form renders identically.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.customers.orm import CustomerItem
from app.leadgen import config, roles
from app.leadgen.models import CustomerLite, RoleGroupOut

# 08062026_cr CR-1: the Generate-Leads modal may ONLY ever surface high-confidence
# customers. Backend is the SSOT — Unsure / No / blank are never returned, no
# matter what the client requests. The user can narrow within this set via the
# two checkboxes; the requested bands are clamped to this allow-list.
ALLOWED_BANDS = ("Sure", "Likely")


def _resolve_bands(bands_sel: list[str] | None) -> list[str]:
    """Clamp a requested band list to the allow-list (Sure/Likely).

    None / empty request → both allowed bands (the default). Any requested value
    outside the allow-list is dropped, so Unsure/No/blank can never leak through.
    """
    if not bands_sel:
        return list(ALLOWED_BANDS)
    keep = [b for b in ALLOWED_BANDS if b in {s.strip() for s in bands_sel}]
    return keep


async def categories(db: AsyncSession) -> list[str]:
    """The live Products & Services category set — distinct brain catalog cats.

    Mirrors `customers.service.mpower_categories` (the Customers categories
    endpoint) so the two surfaces stay in lock-step. Deterministic order.
    """
    try:
        rows = await db.execute(
            text(
                "SELECT DISTINCT category FROM brain_catalog_items "
                "WHERE archived = 0 AND category IS NOT NULL AND category != '' "
                "ORDER BY category"
            )
        )
    except Exception:  # noqa: BLE001 — table absent on a fresh DB → no cats yet
        return []
    cats = [r[0] for r in rows.fetchall() if r[0] and r[0] != "Manual"]
    return sorted(set(cats))


async def categories_grouped(db: AsyncSession) -> dict[str, list[str]]:
    """Distinct catalog categories bucketed Products vs Services by item `kind`.

    Mirrors the mPower-brain Products/Services sub-tabs (which filter catalog
    items on `kind`). A category lands under "product" if it has ANY product
    item, else "service" — deterministic, and the union equals `categories()`
    (same table + filters). Returns {"product": [...sorted], "service": [...]}.
    """
    try:
        rows = await db.execute(
            text(
                "SELECT DISTINCT category, kind FROM brain_catalog_items "
                "WHERE archived = 0 AND category IS NOT NULL AND category != '' "
                "AND category != 'Manual'"
            )
        )
    except Exception:  # noqa: BLE001 — table absent on a fresh DB → no cats yet
        return {"product": [], "service": []}
    kinds: dict[str, set[str]] = {}
    for cat, kind in rows.fetchall():
        if cat:
            kinds.setdefault(cat, set()).add((kind or "").strip().lower())
    products = sorted(c for c, ks in kinds.items() if "product" in ks)
    services = sorted(c for c, ks in kinds.items() if "product" not in ks)
    return {"product": products, "service": services}


async def countries(db: AsyncSession) -> list[str]:
    """Distinct non-empty country values across non-archived customers (sorted)."""
    rows = await db.execute(
        select(CustomerItem.country)
        .where(
            CustomerItem.archived.is_(False),
            CustomerItem.country.isnot(None),
            CustomerItem.country != "",
        )
        .distinct()
    )
    vals = {(r[0] or "").strip() for r in rows.fetchall() if (r[0] or "").strip()}
    return sorted(vals)


def _to_lite(item: CustomerItem) -> CustomerLite:
    return CustomerLite(
        id=item.id,
        name=item.name,
        type=item.ctype,
        country=item.country,
        category=item.category,
        website=item.website,
        band=item.band,
    )


async def all_customers(
    db: AsyncSession, bands_sel: list[str] | None = None
) -> list[CustomerLite]:
    """Non-archived Sure/Likely customers (deterministic order: country, name, id).

    CR-1: the band filter is ALWAYS applied (default Sure+Likely). Unsure/No/blank
    are never returned. `bands_sel` may narrow within the allow-list.
    """
    bands = _resolve_bands(bands_sel)
    if not bands:
        return []
    rows = list(
        (await db.execute(
            select(CustomerItem)
            .where(
                CustomerItem.archived.is_(False),
                CustomerItem.band.in_(bands),
            )
            .order_by(CustomerItem.country, CustomerItem.name, CustomerItem.id)
        )).scalars().all()
    )
    return [_to_lite(it) for it in rows]


async def filtered_customers(
    db: AsyncSession,
    categories_sel: list[str] | None,
    types_sel: list[str] | None,
    country: str | None,
    bands_sel: list[str] | None = None,
) -> list[CustomerLite]:
    """Non-archived customers narrowed by category / type / country / band.

    category in selected (if any) AND ctype in selected types (if any) AND
    country == country (if given) AND band in the allow-list (always — CR-1).
    """
    bands = _resolve_bands(bands_sel)
    if not bands:
        return []
    stmt = select(CustomerItem).where(
        CustomerItem.archived.is_(False),
        CustomerItem.band.in_(bands),
    )
    cats = [c.strip() for c in (categories_sel or []) if c and c.strip()]
    if cats:
        stmt = stmt.where(CustomerItem.category.in_(cats))
    tps = [t.strip() for t in (types_sel or []) if t and t.strip()]
    if tps:
        stmt = stmt.where(CustomerItem.ctype.in_(tps))
    if country and country.strip():
        stmt = stmt.where(CustomerItem.country == country.strip())
    stmt = stmt.order_by(CustomerItem.country, CustomerItem.name, CustomerItem.id)
    rows = list((await db.execute(stmt)).scalars().all())
    return [_to_lite(it) for it in rows]


def role_groups() -> list[RoleGroupOut]:
    """The static decision-maker role taxonomy (group → title variants)."""
    return [RoleGroupOut(group=g, titles=list(titles)) for g, titles in roles.ROLE_GROUPS]


async def assemble(db: AsyncSession):
    """The full ListsResponse payload (categories, types, countries, customers, roles)."""
    return {
        "categories": await categories(db),
        "categories_grouped": await categories_grouped(db),
        "types": list(config.TYPES),
        "countries": await countries(db),
        "customers": await all_customers(db),
        "roles": role_groups(),
    }
