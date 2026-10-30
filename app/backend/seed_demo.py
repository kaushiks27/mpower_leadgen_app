"""Demo seed — 10 synthetic leads so the dashboard is populated for a sales call.

Run from `app/backend`:  .venv/bin/python seed_demo.py

ADDITIVE + IDEMPOTENT (OP #13 — never wipes the dev DB). Creates two clearly
labelled "Demo —" campaigns + 10 leads spread across every pipeline stage (so
the funnel, reply/positive rates, 5k-goal, hot-reply queue and credit-burn
widgets all show real numbers), each carrying a synthetic INR revenue value.
Pushed leads get a `queued` audit event dated now (counts toward this month's
goal). Re-running is a no-op once the demo campaigns exist. The 7 real leads on
campaign 1 are never touched.

All values are fixed literals (deterministic) — nothing is LLM-computed and no
load-bearing pipeline decision is automated; this is display fixture data only.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

import app.db as db_mod
from app.campaigns.orm import Campaign
from app.config.orm import CatalogItem
from app.db import init_db
from app.enrichment.credits import current_period
from app.enrichment.orm import CreditCeiling, CreditUsage
from app.leads.orm import Company, Lead, LeadEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed_demo")

DEMO_CAMPAIGNS = ("Demo — Drone OEMs (India)", "Demo — RPTO Operators (Global)")

# (name, domain)
_COMPANIES = (
    ("SkyForge Aerospace", "skyforge.in"),
    ("Garuda Aerial Systems", "garudaaerial.in"),
    ("Meridian UAV", "meridianuav.com"),
    ("Falcon RPTO Academy", "falconrpto.in"),
    ("NorthWind Robotics", "northwindrobotics.com"),
)

# Per-lead fixture. fields: first, last, title, location, company(idx), stage,
# value_inr (synthetic revenue), email_status, flags, pushed(=queued event).
# Stage spread populates every funnel column + hot-reply queue + the goal.
_LEADS = (
    # Campaign A — Drone OEMs (India)
    dict(first="Aarav", last="Kapoor", title="Head of Procurement", loc="Pune, India",
         company=0, camp=0, stage="won", value=1_250_000, status="valid", pushed=True,
         ice="Saw SkyForge just stood up a second Pune line — sharp scaling."),
    dict(first="Diya", last="Sharma", title="Founder & CEO", loc="Bengaluru, India",
         company=1, camp=0, stage="interested", value=880_000, status="valid", pushed=True,
         ice="Your BVLOS corridor pilot last quarter was genuinely impressive."),
    dict(first="Rohan", last="Iyer", title="VP Engineering", loc="Hyderabad, India",
         company=2, camp=0, stage="replied", value=650_000, status="valid", pushed=True,
         ice="Loved your note on payload modularity in the UAV forum."),
    dict(first="Ananya", last="Reddy", title="Director, Sourcing", loc="Chennai, India",
         company=3, camp=0, stage="emailed", value=420_000, status="valid", pushed=True,
         ice="Falcon's new RPTO cohort numbers caught my eye."),
    dict(first="Vikram", last="Nair", title="R&D Lead", loc="Kochi, India",
         company=4, camp=0, stage="enriched", value=300_000, status="valid", pushed=False,
         ice="Your team's flight-controller writeup was a great read."),
    # Campaign B — RPTO Operators (Global)
    dict(first="Liam", last="O'Brien", title="Operations Director", loc="Dublin, Ireland",
         company=2, camp=1, stage="replied", value=560_000, status="valid", pushed=True,
         ice="Noticed Meridian just added two survey contracts — busy season."),
    dict(first="Sofia", last="Mendes", title="Procurement Manager", loc="Lisbon, Portugal",
         company=4, camp=1, stage="replied", value=210_000, status="valid", pushed=True,
         not_interested=True,
         ice="Saw NorthWind's warehouse-drone rollout — neat use case."),
    dict(first="Noah", last="Becker", title="Fleet Manager", loc="Berlin, Germany",
         company=1, camp=1, stage="emailed", value=190_000, status="risky", pushed=True,
         bounced=True,
         ice="Your fleet-uptime dashboard demo was clean."),
    dict(first="Mia", last="Larsson", title="Chief Pilot", loc="Stockholm, Sweden",
         company=3, camp=1, stage="queued", value=140_000, status="valid", pushed=True,
         ice="Falcon's instructor-led syllabus looks well thought out."),
    dict(first="Ethan", last="Walsh", title="Head of Ops", loc="Toronto, Canada",
         company=0, camp=1, stage="new", value=95_000, status="unknown", pushed=False,
         ice="Saw SkyForge expanding into North America — exciting."),
)

# Synthetic credit consumption so the credit-burn widget shows real bars.
_CREDITS = (("apollo", 2000, 640), ("millionverifier", 1000, 410))


async def _catalog_id(session, kind: str) -> int:
    """First catalog item id of `kind`; create a demo placeholder if none exists."""
    row = (
        await session.execute(
            select(CatalogItem).where(CatalogItem.kind == kind).order_by(CatalogItem.id)
        )
    ).scalars().first()
    if row:
        return row.id
    item = CatalogItem(kind=kind, name=f"Demo {kind}")
    session.add(item)
    await session.flush()
    return item.id


async def seed_demo() -> None:
    await init_db()
    async with db_mod.async_session() as session:
        existing = (
            await session.execute(
                select(Campaign).where(Campaign.name == DEMO_CAMPAIGNS[0])
            )
        ).scalars().first()
        if existing:
            logger.info("demo data already present — nothing to do (idempotent).")
            return

        cat = await _catalog_id(session, "category")
        tgt = await _catalog_id(session, "target_category")
        geo = await _catalog_id(session, "geography")

        # Campaigns (active so they count as active_campaigns).
        camps: list[Campaign] = []
        for i, cname in enumerate(DEMO_CAMPAIGNS):
            c = Campaign(
                name=cname, owner="Kaushik (demo)", category_id=cat,
                target_category_id=tgt, geography_id=geo, target_lead_count=5,
                timezone="Asia/Kolkata", status="active",
            )
            session.add(c)
            camps.append(c)
        await session.flush()

        # Companies.
        companies: list[Company] = []
        for cn, dom in _COMPANIES:
            co = Company(name=cn, domain=dom)
            session.add(co)
            companies.append(co)
        await session.flush()

        # Leads + audit events.
        for i, spec in enumerate(_LEADS, start=1):
            lead = Lead(
                first_name=spec["first"], last_name=spec["last"],
                email=f"{spec['first'].lower()}.{spec['last'].lower().replace(chr(39), '')}@demo.local",
                phone=None, title=spec["title"], location=spec["loc"],
                icebreaker=spec["ice"], value_inr=spec["value"],
                email_status=spec["status"], company_id=companies[spec["company"]].id,
                campaign_id=camps[spec["camp"]].id, dedup_key=f"nc:demo-{i}",
                stage=spec["stage"], source="demo",
                not_interested=bool(spec.get("not_interested")),
                bounced=bool(spec.get("bounced")),
            )
            session.add(lead)
            await session.flush()
            session.add(LeadEvent(
                lead_id=lead.id, kind="created", to_value=spec["stage"],
                actor_name="demo seed",
            ))
            if spec["pushed"]:
                # Dated now → counts toward this month's 5k goal.
                session.add(LeadEvent(
                    lead_id=lead.id, kind="stage_change", from_value="enriched",
                    to_value="queued", actor_name="demo seed",
                ))

        # Credit usage + ceilings.
        period = current_period()
        for provider, limit, used in _CREDITS:
            if not await session.get(CreditCeiling, provider):
                session.add(CreditCeiling(provider=provider, monthly_limit=limit))
            row = (
                await session.execute(
                    select(CreditUsage).where(
                        CreditUsage.provider == provider, CreditUsage.period == period
                    )
                )
            ).scalars().first()
            if row is None:
                session.add(CreditUsage(provider=provider, period=period, used=used))

        await session.commit()
        logger.info("seeded %d demo leads across %d campaigns.", len(_LEADS), len(camps))


if __name__ == "__main__":
    asyncio.run(seed_demo())
