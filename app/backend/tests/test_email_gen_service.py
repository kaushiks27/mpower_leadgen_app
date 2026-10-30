"""S-7 icebreaker job — fake writer (no live Claude call, no spend).

Covers: writes one line per lead with a signal, skips no-signal leads (never
fabricates), is idempotent (re-run writes 0), counts errors without crashing,
and the status snapshot reports missing/no_source/written correctly.
"""

from __future__ import annotations

import json

import pytest_asyncio

from app.email_gen.service import icebreaker_status, run_icebreaker_job
from app.jobs import service as jobs_service

CID = 1


@pytest_asyncio.fixture
async def session(client):
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


async def _seed(session, *, with_signal, n, start=0, campaign_id=CID, email_status="valid"):
    """Seed campaign leads. email_status defaults to 'valid' so they are
    icebreaker-eligible (S-7 gate = verified-valid leads only)."""
    from app.leads.orm import Lead

    for i in range(start, start + n):
        raw = json.dumps({"headline": f"runs drones at Co{i}"}) if with_signal else None
        session.add(
            Lead(
                first_name=f"L{i}",
                last_name="T",
                title="Ops" if with_signal else None,
                campaign_id=campaign_id,
                dedup_key=f"nc:ice-{campaign_id}-{i}",
                stage="enriched",
                source="apify",
                scrape_raw=raw,
                email_status=email_status,
            )
        )
    await session.commit()


async def _writer_ok(system, user):
    return "saw your drone fleet work, quick question for you"


async def _read_leads(campaign_id=CID):
    import app.db as db_mod
    from sqlalchemy import select
    from app.leads.orm import Lead

    async with db_mod.async_session() as s:
        return (
            await s.execute(select(Lead).where(Lead.campaign_id == campaign_id).order_by(Lead.id))
        ).scalars().all()


async def test_writes_one_icebreaker_per_signal_lead(session):
    await _seed(session, with_signal=True, n=3)
    job = await jobs_service.create_job(session, kind="icebreaker", campaign_id=CID)
    await run_icebreaker_job(session, job.id, CID, writer=_writer_ok)

    leads = await _read_leads()
    assert all(l.icebreaker == "saw your drone fleet work, quick question for you" for l in leads)
    import app.db as db_mod
    async with db_mod.async_session() as s:
        j = await jobs_service.get_job(s, job.id)
    assert j.status == "done"
    assert j.created_count == 3
    assert j.credits_used == 0  # Claude is not credit-metered


async def test_no_signal_leads_are_skipped_not_fabricated(session):
    await _seed(session, with_signal=False, n=2)
    job = await jobs_service.create_job(session, kind="icebreaker", campaign_id=CID)
    await run_icebreaker_job(session, job.id, CID, writer=_writer_ok)

    leads = await _read_leads()
    assert all(l.icebreaker is None for l in leads)  # never invented
    import app.db as db_mod
    async with db_mod.async_session() as s:
        j = await jobs_service.get_job(s, job.id)
    assert j.skipped_count == 2
    assert j.created_count == 0


async def test_idempotent_rerun_writes_zero(session):
    await _seed(session, with_signal=True, n=2)
    job1 = await jobs_service.create_job(session, kind="icebreaker", campaign_id=CID)
    await run_icebreaker_job(session, job1.id, CID, writer=_writer_ok)

    calls = {"n": 0}

    async def counting_writer(system, user):
        calls["n"] += 1
        return "second pass line"

    job2 = await jobs_service.create_job(session, kind="icebreaker", campaign_id=CID)
    await run_icebreaker_job(session, job2.id, CID, writer=counting_writer)
    assert calls["n"] == 0  # nothing left to write

    leads = await _read_leads()
    assert all(l.icebreaker == "saw your drone fleet work, quick question for you" for l in leads)


async def test_writer_error_is_counted_not_raised(session):
    await _seed(session, with_signal=True, n=2)

    from app.email_gen.claude_client import ClaudeError

    async def boom(system, user):
        raise ClaudeError("rate limited")

    job = await jobs_service.create_job(session, kind="icebreaker", campaign_id=CID)
    await run_icebreaker_job(session, job.id, CID, writer=boom)

    import app.db as db_mod
    async with db_mod.async_session() as s:
        j = await jobs_service.get_job(s, job.id)
    assert j.status == "done"
    assert j.error_count == 2
    assert j.created_count == 0


async def test_status_reports_missing_no_source_written(session):
    await _seed(session, with_signal=True, n=2, start=0)
    await _seed(session, with_signal=False, n=1, start=100)

    from app.campaigns.orm import Campaign
    campaign = Campaign(
        id=CID, name="c", category_id=1, target_category_id=1, geography_id=1,
        timezone="Asia/Kolkata",
    )
    st = await icebreaker_status(session, campaign)
    assert st.missing == 2
    assert st.no_source == 1
    assert st.written == 0


async def test_unverified_leads_are_not_eligible(session):
    # Leads that have NOT been verified-valid (e.g. still un-enriched) are
    # excluded — the icebreaker button stays disabled until Enrich/verify runs.
    await _seed(session, with_signal=True, n=2, email_status=None)

    from app.campaigns.orm import Campaign
    campaign = Campaign(
        id=CID, name="c", category_id=1, target_category_id=1, geography_id=1,
        timezone="Asia/Kolkata",
    )
    st = await icebreaker_status(session, campaign)
    assert st.missing == 0
    assert st.reason == "needs_enrich"
    assert st.can_generate is False

    # And the job writes nothing for them.
    calls = {"n": 0}

    async def writer(system, user):
        calls["n"] += 1
        return "x"

    job = await jobs_service.create_job(session, kind="icebreaker", campaign_id=CID)
    await run_icebreaker_job(session, job.id, CID, writer=writer)
    assert calls["n"] == 0
    leads = await _read_leads()
    assert all(l.icebreaker is None for l in leads)
