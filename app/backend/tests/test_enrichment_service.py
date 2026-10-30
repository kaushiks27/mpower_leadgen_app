"""Apollo+MV enrich orchestration — fakes for all network I/O (no credits).

Covers: enrich attaches email/phone/status + enriched_at, only `valid` is
eligible, credits are exact integers (1 Apollo + 1 MV per processed lead), no
re-enrich on a second run, no-email leads are flagged, and the Apollo ceiling
stops the run before overspending.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest_asyncio

from app.enrichment import credits
from app.enrichment.service import run_enrich_job
from app.jobs import service as jobs_service

NOW = datetime(2026, 6, 3, tzinfo=timezone.utc)
PERIOD = "2026-06"
CID = 1


@pytest_asyncio.fixture
async def session(client):
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


async def _seed_leads(session, n, *, campaign_id=CID, start=0):
    from app.leads.orm import Lead

    for i in range(start, start + n):
        session.add(
            Lead(
                first_name=f"L{i}",
                last_name="Test",
                campaign_id=campaign_id,
                dedup_key=f"nc:test-{i}",
                stage="new",
                source="apify",
            )
        )
    await session.commit()


async def _noop_warner(provider, used, limit):
    return None


async def _verifier_valid(email):
    return "valid"


async def test_enrich_attaches_email_status_and_counts_credits(session):
    await _seed_leads(session, 3)
    job = await jobs_service.create_job(session, kind="apollo_enrich", campaign_id=CID)

    async def matcher(h):
        return {"email": f"{h['first_name']}@x.com", "phone": "+1 555", "headline": "H", "title": None}

    await run_enrich_job(
        session, job.id, CID, 25,
        matcher=matcher, verifier=_verifier_valid, warner=_noop_warner, now=NOW,
    )

    # Fresh session: read what actually persisted.
    import app.db as db_mod
    from sqlalchemy import select
    from app.leads.orm import Lead

    async with db_mod.async_session() as s2:
        leads = (await s2.execute(select(Lead).where(Lead.campaign_id == CID))).scalars().all()
        assert len(leads) == 3
        for l in leads:
            assert l.email and l.email.endswith("@x.com")
            assert l.phone == "+1 555"
            assert l.email_status == "valid"
            assert l.enriched_at is not None
        j = await jobs_service.get_job(s2, job.id)
        assert j.status == "done"
        assert j.created_count == 3
        # Exactly 1 Apollo + 1 MV credit per processed lead.
        assert await credits.get_usage(s2, "apollo", PERIOD) == 3
        assert await credits.get_usage(s2, "millionverifier", PERIOD) == 3


async def test_only_valid_is_eligible(session):
    await _seed_leads(session, 2)
    job = await jobs_service.create_job(session, kind="apollo_enrich", campaign_id=CID)

    async def matcher(h):
        return {"email": f"{h['first_name']}@x.com", "phone": None, "headline": None, "title": None}

    async def verifier(email):
        return "valid" if email.startswith("L0") else "invalid"

    await run_enrich_job(
        session, job.id, CID, 25,
        matcher=matcher, verifier=verifier, warner=_noop_warner, now=NOW,
    )

    import app.db as db_mod
    from sqlalchemy import select
    from app.leads.orm import Lead

    async with db_mod.async_session() as s2:
        leads = (await s2.execute(select(Lead).where(Lead.campaign_id == CID))).scalars().all()
        statuses = {l.first_name: l.email_status for l in leads}
        assert statuses["L0"] == "valid"
        assert statuses["L1"] == "invalid"  # carries the "unverified" meaning


async def test_no_re_enrich_spends_zero(session):
    await _seed_leads(session, 2)

    async def matcher(h):
        return {"email": f"{h['first_name']}@x.com", "phone": None, "headline": None, "title": None}

    job1 = await jobs_service.create_job(session, kind="apollo_enrich", campaign_id=CID)
    await run_enrich_job(session, job1.id, CID, 25, matcher=matcher, verifier=_verifier_valid, warner=_noop_warner, now=NOW)

    import app.db as db_mod
    async with db_mod.async_session() as s2:
        before = await credits.get_usage(s2, "apollo", PERIOD)
        assert before == 2

    # Second run: every lead already enriched -> nothing processed, no credits.
    async with db_mod.async_session() as s3:
        job2 = await jobs_service.create_job(s3, kind="apollo_enrich", campaign_id=CID)
        await run_enrich_job(s3, job2.id, CID, 25, matcher=matcher, verifier=_verifier_valid, warner=_noop_warner, now=NOW)
        j2 = await jobs_service.get_job(s3, job2.id)
        assert j2.processed == 0 and j2.created_count == 0
        assert await credits.get_usage(s3, "apollo", PERIOD) == 2  # unchanged


async def test_no_email_flagged_no_email(session):
    await _seed_leads(session, 1)
    job = await jobs_service.create_job(session, kind="apollo_enrich", campaign_id=CID)

    async def matcher(h):
        return {"email": None, "phone": None, "headline": None, "title": None}

    async def verifier(email):  # should never be called
        raise AssertionError("verifier called for a no-email lead")

    await run_enrich_job(session, job.id, CID, 25, matcher=matcher, verifier=verifier, warner=_noop_warner, now=NOW)

    import app.db as db_mod
    from sqlalchemy import select
    from app.leads.orm import Lead

    async with db_mod.async_session() as s2:
        lead = (await s2.execute(select(Lead).where(Lead.campaign_id == CID))).scalars().first()
        assert lead.email_status == "no_email"
        assert lead.enriched_at is not None  # still marked, won't re-enrich
        # Apollo charged (call was made), MV not (no email).
        assert await credits.get_usage(s2, "apollo", PERIOD) == 1
        assert await credits.get_usage(s2, "millionverifier", PERIOD) == 0


async def test_apollo_ceiling_stops_run(session):
    await _seed_leads(session, 5)
    await credits.set_ceiling(session, "apollo", 2)
    job = await jobs_service.create_job(session, kind="apollo_enrich", campaign_id=CID)

    async def matcher(h):
        return {"email": f"{h['first_name']}@x.com", "phone": None, "headline": None, "title": None}

    await run_enrich_job(session, job.id, CID, 25, matcher=matcher, verifier=_verifier_valid, warner=_noop_warner, now=NOW)

    import app.db as db_mod
    async with db_mod.async_session() as s2:
        # Stopped at the ceiling: never spent past 2 Apollo credits.
        assert await credits.get_usage(s2, "apollo", PERIOD) == 2
        j = await jobs_service.get_job(s2, job.id)
        assert j.status == "done"
        assert "ceiling" in (j.message or "").lower()
