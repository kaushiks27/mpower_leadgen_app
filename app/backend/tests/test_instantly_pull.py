"""S-9 Instantly pull — pure status mapper + Sync orchestration.

Fake client (no live API, no spend/send). Covers: deterministic classify/forward
mapping, forward-only stage moves, bounce/unsub flag + auto-suppress, idempotent
re-sync (zero writes), email matching, unmatched counting, and the not-pushed gate.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.instantly import pull_mapper, puller
from app.instantly.orm import InstantlyCampaign
from app.leads.orm import Lead, LeadEvent
from app.suppression.orm import SuppressionEntry

CID = 1


# --- Pure mapper (no DB) ------------------------------------------------------


def _raw(email="a@co.com", status=1, replies=0, opens=0, clicks=0):
    return {
        "email": email,
        "status": status,
        "email_reply_count": replies,
        "email_open_count": opens,
        "email_click_count": clicks,
    }


def test_classify_reply_is_verified_signal():
    s = pull_mapper.classify_lead(_raw(replies=2))
    assert s.replied is True and s.engaged is True and s.reply_count == 2


def test_classify_engaged_from_open_only():
    s = pull_mapper.classify_lead(_raw(opens=1))
    assert s.engaged is True and s.replied is False


def test_classify_email_normalized_lowercase():
    assert pull_mapper.classify_lead(_raw(email="  A@CO.com "))   .email == "a@co.com"


def test_classify_bounce_and_unsub_unverified_codes():
    assert pull_mapper.classify_lead(_raw(status=-1)).bounced is True
    assert pull_mapper.classify_lead(_raw(status=3)).unsubscribed is True
    # an UNKNOWN status takes no action (never mis-suppress a good lead)
    unknown = pull_mapper.classify_lead(_raw(status=2))
    assert unknown.bounced is False and unknown.unsubscribed is False


def test_forward_stage_is_forward_only():
    s_reply = pull_mapper.classify_lead(_raw(replies=1))
    assert pull_mapper.forward_stage("queued", s_reply) == "replied"
    # already past replied → never regress
    assert pull_mapper.forward_stage("won", s_reply) is None
    # engaged-only advances queued→emailed, not to replied
    s_sent = pull_mapper.classify_lead(_raw(opens=1))
    assert pull_mapper.forward_stage("queued", s_sent) == "emailed"
    # no signal → no move
    assert pull_mapper.forward_stage("queued", pull_mapper.classify_lead(_raw())) is None


# --- Puller (DB + fake client) ------------------------------------------------


@pytest_asyncio.fixture
async def session(client, monkeypatch):
    monkeypatch.setenv("INSTANTLY_API_KEY", "test-key")
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


class FakeClient:
    """Returns a fixed list of raw Instantly lead dicts for list_leads."""

    def __init__(self, raw_leads):
        self._raw = raw_leads

    async def list_leads(self, instantly_campaign_id):
        return list(self._raw)


async def _user(session):
    from app.auth.orm import User
    from app.auth.passwords import hash_password

    u = User(email="admin@x.com", password_hash=hash_password("x"), role="admin",
             first_name="Ada", last_name="Min")
    session.add(u)
    await session.commit()
    await session.refresh(u)
    return u


async def _campaign(session):
    from app.campaigns.orm import Campaign

    c = Campaign(id=CID, name="Drone OEMs", category_id=1, target_category_id=1,
                 geography_id=1, timezone="Asia/Kolkata", send_days="mon,tue",
                 send_start_hour=9, send_end_hour=17)
    session.add(c)
    # mark as pushed (draft) so Sync is allowed
    session.add(InstantlyCampaign(campaign_id=CID, instantly_campaign_id="inst-abc",
                                  status="draft", leads_pushed=1))
    await session.commit()
    return c


async def _lead(session, i, *, email, stage="queued", bounced=False, unsubscribed=False):
    lead = Lead(first_name=f"L{i}", last_name="T", email=email, campaign_id=CID,
                dedup_key=f"nc:pull-{i}", stage=stage, source="apify",
                email_status="valid", bounced=bounced, unsubscribed=unsubscribed)
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    return lead


async def test_sync_reply_advances_stage_with_audit(session):
    c = await _campaign(session)
    u = await _user(session)
    lead = await _lead(session, 1, email="a@co.com", stage="queued")

    fake = FakeClient([_raw(email="a@co.com", replies=1)])
    res = await puller.sync_campaign(session, c, user=u, client=fake)

    assert res.stage_changes == 1
    await session.refresh(lead)
    assert lead.stage == "replied"
    ev = (await session.execute(
        select(LeadEvent).where(LeadEvent.kind == "stage_change",
                                LeadEvent.to_value == "replied")
    )).scalars().all()
    assert len(ev) == 1
    assert ev[0].actor_user_id == u.id and "Instantly sync" in (ev[0].actor_name or "")


async def test_sync_is_forward_only_no_regress(session):
    c = await _campaign(session)
    u = await _user(session)
    lead = await _lead(session, 1, email="a@co.com", stage="won")  # manually advanced

    fake = FakeClient([_raw(email="a@co.com", replies=1)])
    res = await puller.sync_campaign(session, c, user=u, client=fake)

    assert res.stage_changes == 0
    await session.refresh(lead)
    assert lead.stage == "won"  # never regressed to replied


async def test_sync_bounce_flags_and_suppresses(session):
    c = await _campaign(session)
    u = await _user(session)
    lead = await _lead(session, 1, email="a@co.com", stage="emailed")

    fake = FakeClient([_raw(email="a@co.com", status=-1)])
    res = await puller.sync_campaign(session, c, user=u, client=fake)

    assert res.newly_bounced == 1 and res.suppressed == 1
    await session.refresh(lead)
    assert lead.bounced is True
    sup = (await session.execute(
        select(SuppressionEntry).where(SuppressionEntry.value == "a@co.com")
    )).scalars().first()
    assert sup is not None and sup.active is True and sup.reason == "bounce"


async def test_sync_unsub_flags_and_suppresses(session):
    c = await _campaign(session)
    u = await _user(session)
    lead = await _lead(session, 1, email="a@co.com", stage="emailed")

    fake = FakeClient([_raw(email="a@co.com", status=3)])
    res = await puller.sync_campaign(session, c, user=u, client=fake)

    assert res.newly_unsubscribed == 1 and res.suppressed == 1
    await session.refresh(lead)
    assert lead.unsubscribed is True


async def test_resync_is_idempotent_zero_writes(session):
    c = await _campaign(session)
    u = await _user(session)
    await _lead(session, 1, email="a@co.com", stage="queued")

    fake = FakeClient([_raw(email="a@co.com", replies=1, status=-1)])
    await puller.sync_campaign(session, c, user=u, client=fake)
    res2 = await puller.sync_campaign(session, c, user=u, client=fake)

    assert res2.stage_changes == 0
    assert res2.newly_bounced == 0
    assert res2.suppressed == 0
    # exactly one stage_change + one flag_change event total (from the FIRST sync)
    evs = (await session.execute(select(LeadEvent))).scalars().all()
    assert sum(1 for e in evs if e.kind == "stage_change") == 1
    assert sum(1 for e in evs if e.kind == "flag_change") == 1


async def test_sync_matches_email_case_insensitively(session):
    c = await _campaign(session)
    u = await _user(session)
    lead = await _lead(session, 1, email="A@Co.com", stage="queued")

    fake = FakeClient([_raw(email="a@co.com", replies=1)])
    res = await puller.sync_campaign(session, c, user=u, client=fake)

    assert res.leads_matched == 1 and res.stage_changes == 1
    await session.refresh(lead)
    assert lead.stage == "replied"


async def test_sync_counts_unmatched_without_error(session):
    c = await _campaign(session)
    u = await _user(session)
    await _lead(session, 1, email="a@co.com", stage="queued")

    fake = FakeClient([_raw(email="a@co.com"), _raw(email="ghost@co.com", replies=1)])
    res = await puller.sync_campaign(session, c, user=u, client=fake)

    assert res.leads_matched == 1
    assert res.leads_unmatched == 1


async def test_sync_not_pushed_raises(session):
    from app.campaigns.orm import Campaign

    c = Campaign(id=2, name="X", category_id=1, target_category_id=1, geography_id=1,
                 timezone="Asia/Kolkata", send_days="mon", send_start_hour=9, send_end_hour=17)
    session.add(c)
    await session.commit()
    u = await _user(session)

    with pytest.raises(puller.SyncError):
        await puller.sync_campaign(session, c, user=u, client=FakeClient([]))


async def test_monitor_snapshot_derives_counts(session):
    c = await _campaign(session)
    u = await _user(session)
    await _lead(session, 1, email="a@co.com", stage="replied")
    await _lead(session, 2, email="b@co.com", stage="emailed")
    await _lead(session, 3, email="c@co.com", stage="emailed", bounced=True)

    mon = await puller.build_monitor(session, c)
    assert mon.leads_total == 3
    assert mon.emailed == 3   # replied + emailed both >= emailed index
    assert mon.replied == 1
    assert mon.bounced == 1
    assert mon.can_sync is True
    assert len(mon.hot_replies) == 1 and mon.hot_replies[0].email == "a@co.com"
