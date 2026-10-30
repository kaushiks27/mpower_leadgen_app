"""Read-only "lead mix" + derived send-timezone for a campaign (08062026_cr CR-3/5).

After CR-3 a campaign no longer carries hand-picked category / target / geography
dropdowns. Instead those facts are DERIVED from the leads pulled into it: the
distinct categories, customer types (OEM/Reseller/Distributor), and countries the
campaign's leads span, plus the send timezone for the majority country.

One-way reads only (campaigns → leads + infra). Deterministic + exact: distinct
values are sorted; the timezone is the deterministic country→IANA majority map.
No LLM, no float.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.timezones import majority_timezone
from app.leads.orm import Lead


async def _campaign_lead_facts(
    db: AsyncSession, campaign_id: int
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return (categories, customer_types, countries-distinct, countries-raw).

    countries-raw keeps duplicates (one per lead) so the timezone majority is
    computed correctly; the distinct lists are for display.
    """
    rows = (
        await db.execute(
            select(Lead.category, Lead.customer_type, Lead.location).where(
                Lead.campaign_id == campaign_id,
                Lead.archived.is_(False),
            )
        )
    ).all()
    cats: set[str] = set()
    types: set[str] = set()
    countries_distinct: set[str] = set()
    countries_raw: list[str] = []
    for category, ctype, country in rows:
        if category and category.strip():
            cats.add(category.strip())
        if ctype and ctype.strip():
            types.add(ctype.strip())
        if country and country.strip():
            countries_distinct.add(country.strip())
            countries_raw.append(country.strip())
    return (
        sorted(cats),
        sorted(types),
        sorted(countries_distinct),
        countries_raw,
    )


async def derive_timezone(db: AsyncSession, campaign_id: int) -> str:
    """The campaign's send timezone derived from its leads' majority country."""
    _, _, _, countries_raw = await _campaign_lead_facts(db, campaign_id)
    return majority_timezone(countries_raw)


async def lead_mix(db: AsyncSession, campaign_id: int) -> dict:
    """Read-only summary of a campaign's lead mix + derived timezone + count."""
    cats, types, countries, countries_raw = await _campaign_lead_facts(
        db, campaign_id
    )
    return {
        "categories": cats,
        "customer_types": types,
        "countries": countries,
        "timezone": majority_timezone(countries_raw),
        "lead_count": await _lead_count(db, campaign_id),
    }


async def _lead_count(db: AsyncSession, campaign_id: int) -> int:
    from sqlalchemy import func as _func

    return int(
        (
            await db.execute(
                select(_func.count())
                .select_from(Lead)
                .where(Lead.campaign_id == campaign_id, Lead.archived.is_(False))
            )
        ).scalar()
        or 0
    )
