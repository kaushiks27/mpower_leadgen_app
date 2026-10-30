"""Best-effort backfill of the CR-6 structured lead taxonomy (08062026_cr).

Existing leads created before CR-6 carry no `category` / `customer_type` /
`customer_item_id` link. This module matches each unattributed lead to the
CustomerItem it most likely came from — by the lead's EMAIL domain first (the
most reliably-present signal: a work email sits on the company's own domain),
then by registrable company domain, then by normalized company name — and fills
the fields (plus `location` <- customer country) where a match is found.
Unmatched leads stay blank.

Deterministic + idempotent (OP #6/#13): only leads with NO `customer_item_id`
are touched, matching is a pure dict lookup, and re-running changes nothing once
attributed. No float, no LLM — this is data plumbing, never a load-bearing number
or pipeline decision. Runs once on boot (a no-op when there is nothing to fill).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.customers.orm import CustomerItem
from app.leadgen import membership
from app.leads.orm import Company, Lead


def _norm_name(name: str | None) -> str:
    return " ".join((name or "").strip().lower().split())


def _email_domain(email: str | None) -> str:
    """Registrable domain of a lead's email (e.g. mia@wing.com -> wing.com)."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return ""
    return membership.registrable(e.rsplit("@", 1)[1])


async def backfill_lead_taxonomy(db: AsyncSession) -> int:
    """Fill category/customer_type/location/customer_item_id on unattributed leads.

    Returns the number of leads updated. Matches by registrable company domain,
    then by normalized company name. Idempotent.
    """
    leads = list(
        (
            await db.execute(
                select(Lead).where(Lead.customer_item_id.is_(None))
            )
        ).scalars().all()
    )
    if not leads:
        return 0

    customers = list(
        (
            await db.execute(
                select(CustomerItem).where(CustomerItem.archived.is_(False))
            )
        ).scalars().all()
    )
    if not customers:
        return 0

    # Build deterministic lookup maps (first-writer-wins on collision, ordered by
    # id so the result is stable across runs).
    by_domain: dict[str, CustomerItem] = {}
    by_name: dict[str, CustomerItem] = {}
    for cust in sorted(customers, key=lambda c: c.id):
        reg = membership.registrable(cust.domain) or membership.registrable(cust.website)
        if reg:
            by_domain.setdefault(reg, cust)
        nm = _norm_name(cust.name)
        if nm:
            by_name.setdefault(nm, cust)

    # Resolve each lead's company once.
    company_ids = {ld.company_id for ld in leads if ld.company_id is not None}
    companies: dict[int, Company] = {}
    if company_ids:
        rows = (
            await db.execute(select(Company).where(Company.id.in_(company_ids)))
        ).scalars().all()
        companies = {c.id: c for c in rows}

    updated = 0
    for ld in leads:
        match: CustomerItem | None = None
        # 1) Strongest signal: the lead's own email domain (almost always present
        #    and sits on the company's registrable domain).
        edom = _email_domain(ld.email)
        if edom:
            match = by_domain.get(edom)
        # 2) Fall back to the company's stored domain, then its exact name.
        company = companies.get(ld.company_id) if ld.company_id is not None else None
        if match is None and company is not None:
            reg = membership.registrable(company.domain)
            if reg:
                match = by_domain.get(reg)
            if match is None:
                match = by_name.get(_norm_name(company.name))
        if match is None:
            continue
        ld.customer_item_id = match.id
        ld.category = match.category
        ld.customer_type = match.ctype
        if match.country:
            ld.location = match.country
        updated += 1

    if updated:
        await db.commit()
    return updated
