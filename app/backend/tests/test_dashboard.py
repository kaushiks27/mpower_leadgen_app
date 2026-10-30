"""S-10 Dashboard — deterministic aggregation + read-only endpoint.

Covers: exact rate math (Decimal, ROUND_HALF_UP), per-campaign funnel counts +
All-campaigns total, contacted/replied/positive classification (not_interested
excluded from positive), 5k-goal counting from queued audit events, credit-burn
read, hot-reply queue ordering, and auth gating (any signed-in user; 401 when out).
No DB writes from the dashboard path.
"""

from __future__ import annotations

import pytest_asyncio

from app.dashboard.aggregator import _rate, build_summary
from app.leads.orm import Lead, LeadEvent

from tests.conftest import login, make_user


# --- Pure rate math (no DB) ---------------------------------------------------


def test_rate_zero_denominator_is_zero():
    assert _rate(5, 0) == 0.0


def test_rate_round_half_up_one_dp():
    # 1/3 = 33.33.. -> 33.3 ; 2/3 = 66.66.. -> 66.7
    assert _rate(1, 3) == 33.3
    assert _rate(2, 3) == 66.7


def test_rate_exact_half_rounds_up():
    # 1/8 = 12.5 exactly -> stays 12.5 ; 1/16 = 6.25 -> 6.3 (half up)
    assert _rate(1, 8) == 12.5
    assert _rate(1, 16) == 6.3


# --- DB fixtures --------------------------------------------------------------


@pytest_asyncio.fixture
async def session(client, monkeypatch):
    """Async session bound to the same temp DB the client fixture set up."""
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


async def _campaign(session, cid, name, status="active"):
    from app.campaigns.orm import Campaign

    c = Campaign(
        id=cid, name=name, category_id=1, target_category_id=1, geography_id=1,
        timezone="Asia/Kolkata", send_days="mon,tue", send_start_hour=9,
        send_end_hour=17, status=status,
    )
    session.add(c)
    await session.commit()
    return c


async def _lead(session, i, *, cid, stage, value_inr=None, not_interested=False,
                bounced=False, queued_event=False, company_id=None):
    lead = Lead(
        first_name=f"L{i}", last_name="T", email=f"l{i}@co.com", campaign_id=cid,
        dedup_key=f"nc:dash-{i}", stage=stage, source="demo", email_status="valid",
        value_inr=value_inr, not_interested=not_interested, bounced=bounced,
        company_id=company_id,
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    if queued_event:
        session.add(LeadEvent(lead_id=lead.id, kind="stage_change", to_value="queued"))
        await session.commit()
    return lead


# --- Aggregator ---------------------------------------------------------------


async def test_funnel_counts_and_total_row(session):
    await _campaign(session, 1, "Drone OEMs")
    await _campaign(session, 2, "RPTO Ops")
    await _lead(session, 1, cid=1, stage="new")
    await _lead(session, 2, cid=1, stage="emailed")
    await _lead(session, 3, cid=2, stage="won")

    summary = await build_summary(session)

    # per-campaign rows ordered by id, then the All-campaigns total last
    assert summary.funnels[-1].campaign_name == "All campaigns"
    assert summary.funnels[-1].total == 3
    assert summary.funnels[-1].stages["new"] == 1
    assert summary.funnels[-1].stages["emailed"] == 1
    assert summary.funnels[-1].stages["won"] == 1
    c1 = next(f for f in summary.funnels if f.campaign_id == 1)
    assert c1.total == 2
    assert summary.active_campaigns == 2


async def test_reply_and_positive_rates_exclude_not_interested(session):
    await _campaign(session, 1, "C1")
    # contacted denominator = emailed-or-beyond. 4 contacted total.
    await _lead(session, 1, cid=1, stage="emailed")  # contacted, no reply
    await _lead(session, 2, cid=1, stage="replied")  # reply + positive
    await _lead(session, 3, cid=1, stage="interested")  # reply + positive
    await _lead(session, 4, cid=1, stage="replied", not_interested=True)  # reply, NOT positive

    summary = await build_summary(session)
    total = summary.funnels[-1]
    assert total.contacted == 4
    assert total.replied == 3  # replied/interested stages
    assert total.positive == 2  # minus the not_interested one
    assert total.reply_rate == 75.0  # 3/4
    assert total.positive_rate == 50.0  # 2/4


async def test_goal_counts_only_queued_events_this_month(session):
    await _campaign(session, 1, "C1")
    await _lead(session, 1, cid=1, stage="queued", queued_event=True)
    await _lead(session, 2, cid=1, stage="emailed", queued_event=True)
    await _lead(session, 3, cid=1, stage="new")  # never pushed → not counted

    summary = await build_summary(session)
    assert summary.goal.pushed_this_month == 2
    assert summary.goal.goal == 5000
    assert summary.goal.pct == 0  # 2/5000 floors to 0


async def test_hot_replies_ordered_by_value_desc(session):
    await _campaign(session, 1, "C1")
    await _lead(session, 1, cid=1, stage="replied", value_inr=100000)
    await _lead(session, 2, cid=1, stage="replied", value_inr=500000)
    await _lead(session, 3, cid=1, stage="replied", value_inr=None)
    await _lead(session, 4, cid=1, stage="won")  # not a hot reply

    summary = await build_summary(session)
    vals = [h.value_inr for h in summary.hot_replies]
    assert vals == [500000, 100000, None]
    assert all(h.unibox_url.startswith("https://app.instantly.ai") for h in summary.hot_replies)


async def test_credit_burn_reads_ceiling_and_usage(session):
    from app.enrichment.credits import current_period, record_usage, set_ceiling

    period = current_period()
    await set_ceiling(session, "apollo", 1000)
    await record_usage(session, "apollo", period, 250)

    summary = await build_summary(session)
    apollo = next(c for c in summary.credit_burn if c.provider == "apollo")
    assert apollo.used == 250 and apollo.limit == 1000 and apollo.pct == 25
    mv = next(c for c in summary.credit_burn if c.provider == "millionverifier")
    assert mv.limit == 0 and mv.unlimited is True


# --- Endpoint auth ------------------------------------------------------------


async def test_summary_requires_auth(client):
    res = await client.get("/api/dashboard/summary")
    assert res.status_code == 401


async def test_summary_visible_to_rep(client):
    await make_user(client, "rep@x.com", "pw12345678", role="rep")
    await login(client, "rep@x.com", "pw12345678")
    res = await client.get("/api/dashboard/summary")
    assert res.status_code == 200
    body = res.json()
    assert "funnels" in body and "goal" in body and "hot_replies" in body
    assert body["goal"]["goal"] == 5000
