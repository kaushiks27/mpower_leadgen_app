"""Idempotent sample-lead seed — visual-verify data only (S-4).

Real leads arrive from the scrapers at S-5/S-6; until then this seeds ~8 clearly
labeled sample leads (source="seed") so the list + board are clickable. The seed
runs every raw record through `dedup_key`, so the planted duplicate collapses to
one lead (proving global dedup). One seeded lead is also added to the suppression
list so the "suppressed" badge is demonstrable.

Skips entirely if ANY lead already exists (never clobbers real/scraped data, OP
#13). Runs from FastAPI lifespan after init_db, gated on SEED_SAMPLE_LEADS=true.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.leads.dedup import dedup_key
from app.leads.orm import Company, Lead, LeadEvent
from app.suppression.normalize import normalize_email
from app.suppression.orm import SuppressionEntry

logger = logging.getLogger(__name__)

# (company_name, domain)
_COMPANIES: tuple[tuple[str, str | None], ...] = (
    ("SkyHarvest Agritech", "skyharvest.in"),
    ("AeroFleet Drones", "aerofleet.io"),
    ("Bharat UAV Systems", "bharatuav.in"),
    ("NimbusWorks", "nimbusworks.com"),
)

# Raw sample records (pre-dedup). Note the planted DUPLICATE: rows 1 and 9 share
# the same LinkedIn URL -> they must collapse to a single lead.
# fields: first, last, email, linkedin, title, location, company, stage, flags
_RAW: tuple[dict, ...] = (
    {
        "first_name": "Aarav", "last_name": "Mehta",
        "email": "aarav@skyharvest.in", "phone": "+91 98200 11111",
        "linkedin_url": "https://www.linkedin.com/in/aarav-mehta",
        "icebreaker": "Saw SkyHarvest just opened a Pune line — clean timing.",
        "title": "Head of Procurement", "location": "Pune, India",
        "company": "SkyHarvest Agritech", "stage": "new",
    },
    {
        "first_name": "Priya", "last_name": "Nair",
        "email": "priya.nair@aerofleet.io", "phone": "+91 99000 22222",
        "linkedin_url": "https://linkedin.com/in/priya-nair-fleet",
        "icebreaker": "Loved your take on fleet uptime in that podcast.",
        "title": "Founder & CEO", "location": "Bengaluru, India",
        "company": "AeroFleet Drones", "stage": "enriched",
    },
    {
        "first_name": "Rohan", "last_name": "Desai",
        "email": "rohan.desai@bharatuav.in", "phone": "+91 90040 33333",
        "linkedin_url": "https://www.linkedin.com/in/rohan-desai-uav",
        "icebreaker": "Your BVLOS demo last month was genuinely impressive.",
        "title": "R&D Lead", "location": "Hyderabad, India",
        "company": "Bharat UAV Systems", "stage": "queued",
    },
    {
        "first_name": "Sara", "last_name": "Khan",
        "email": "sara.khan@nimbusworks.com", "phone": "+971 50 444 5555",
        "linkedin_url": "https://linkedin.com/in/sara-khan-ops",
        "icebreaker": "Noticed NimbusWorks is scaling ops across the Gulf — nice.",
        "title": "Operations Director", "location": "Dubai, UAE",
        "company": "NimbusWorks", "stage": "emailed",
    },
    {
        "first_name": "Vikram", "last_name": "Rao",
        "email": "vikram.rao@bharatuav.in", "phone": "+91 98490 55555",
        "linkedin_url": "https://www.linkedin.com/in/vikram-rao-supply",
        "icebreaker": "Your post on supplier lead-times hit close to home.",
        "title": "Supply Chain Manager", "location": "Hyderabad, India",
        "company": "Bharat UAV Systems", "stage": "replied",
    },
    {
        "first_name": "Meera", "last_name": "Iyer",
        "email": "meera@skyharvest.in", "phone": "+91 98201 66666",
        "linkedin_url": "https://linkedin.com/in/meera-iyer",
        "icebreaker": "Big fan of how SkyHarvest keeps it founder-led.",
        "title": "Co-founder", "location": "Pune, India",
        "company": "SkyHarvest Agritech", "stage": "interested",
    },
    {
        "first_name": "Daniel", "last_name": "Brooks",
        "email": "daniel.brooks@aerofleet.io", "phone": "+1 512 777 8888",
        "linkedin_url": "https://linkedin.com/in/daniel-brooks-fleet",
        "icebreaker": "Your Austin hardware meetup looked like a blast.",
        "title": "VP Engineering", "location": "Austin, USA",
        "company": "AeroFleet Drones", "stage": "won",
    },
    {
        "first_name": "Anjali", "last_name": "Gupta",
        "email": "anjali.gupta@nimbusworks.com", "phone": "+65 8123 4567",
        "linkedin_url": "https://www.linkedin.com/in/anjali-gupta-maint",
        "icebreaker": "Respect how you keep a fleet flying with a small crew.",
        "title": "Maintenance Lead", "location": "Singapore",
        "company": "NimbusWorks", "stage": "emailed",
        "flags": {"bounced": True},
    },
    # PLANTED DUPLICATE of row 1 (same LinkedIn URL, different casing/format).
    {
        "first_name": "Aarav", "last_name": "Mehta",
        "email": "aarav@skyharvest.in", "phone": "+91 98200 11111",
        "linkedin_url": "http://LinkedIn.com/in/Aarav-Mehta/",
        "title": "Head of Procurement", "location": "Pune",
        "company": "SkyHarvest Agritech", "stage": "new",
    },
)

# One seeded lead (by email) goes on the do-not-contact list -> "suppressed" badge.
_SUPPRESS_EMAIL = "sara.khan@nimbusworks.com"


async def seed_sample_leads_if_missing() -> None:
    import app.db as db_mod  # re-import so test fixtures swapping the engine win

    async with db_mod.async_session() as db:
        count = (await db.execute(select(func.count(Lead.id)))).scalar_one()
        if count and count > 0:
            return  # never clobber existing/scraped leads (OP #13)

        # Companies first (so we can FK leads to them).
        companies: dict[str, Company] = {}
        for name, domain in _COMPANIES:
            c = Company(name=name, domain=domain)
            db.add(c)
            companies[name] = c
        await db.flush()  # assign company ids

        seen: set[str] = set()
        created = 0
        for raw in _RAW:
            key = dedup_key(
                first_name=raw.get("first_name"),
                last_name=raw.get("last_name"),
                email=raw.get("email"),
                linkedin_url=raw.get("linkedin_url"),
                company_name=raw.get("company"),
            )
            if key in seen:
                continue  # planted duplicate collapses here
            seen.add(key)
            flags = raw.get("flags", {})
            lead = Lead(
                first_name=raw["first_name"],
                last_name=raw["last_name"],
                email=raw.get("email"),
                phone=raw.get("phone"),
                linkedin_url=raw.get("linkedin_url"),
                icebreaker=raw.get("icebreaker"),
                title=raw.get("title"),
                location=raw.get("location"),
                company_id=companies[raw["company"]].id,
                dedup_key=key,
                stage=raw.get("stage", "new"),
                bounced=flags.get("bounced", False),
                unsubscribed=flags.get("unsubscribed", False),
                not_interested=flags.get("not_interested", False),
                source="seed",
            )
            db.add(lead)
            await db.flush()
            db.add(
                LeadEvent(
                    lead_id=lead.id,
                    kind="created",
                    to_value=lead.stage,
                    actor_name="seed",
                )
            )
            created += 1

        # Suppression demo entry (idempotent: only if not already present).
        norm = normalize_email(_SUPPRESS_EMAIL)
        if norm:
            exists = (
                await db.execute(
                    select(SuppressionEntry).where(
                        SuppressionEntry.kind == "email",
                        SuppressionEntry.value == norm,
                    )
                )
            ).scalars().first()
            if exists is None:
                db.add(
                    SuppressionEntry(
                        kind="email",
                        value=norm,
                        reason="sample",
                        active=True,
                        created_by_name="seed",
                    )
                )

        await db.commit()
        logger.info("seed_sample_leads: inserted %d leads (deduped)", created)
