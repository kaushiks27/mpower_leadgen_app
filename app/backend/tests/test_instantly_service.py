"""S-8 Instantly push service — fake client (no live API, no send/spend).

Covers: the all-ready gate (eligible/pending/excluded + reasons), the push job
(creates draft, uploads eligible leads, flips them forward to queued with an audit
event), the re-push lock, and start (activate → live, idempotent, error pill).
"""

from __future__ import annotations

import pytest_asyncio

from app.instantly.service import (
    PushError,
    push_status,
    run_push_job,
    start_campaign,
)
from app.instantly.client import InstantlyError
from app.jobs import service as jobs_service

CID = 1


@pytest_asyncio.fixture
async def session(client, monkeypatch):
    # A saved Instantly key so the gate's missing_key branch is satisfied.
    monkeypatch.setenv("INSTANTLY_API_KEY", "test-key")
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


class FakeClient:
    """Records calls; returns a fixed campaign id. Optionally raises.

    `fail_lead_emails` fails the WHOLE bulk batch if any listed email is in it
    (mirrors Instantly's per-request semantics for the test)."""

    def __init__(self, *, fail_create=False, fail_lead_emails=None, fail_activate=False):
        self.fail_create = fail_create
        self.fail_lead_emails = set(fail_lead_emails or [])
        self.fail_activate = fail_activate
        self.created = None
        self.leads = []  # flattened lead entries successfully added
        self.batches = []  # (campaign_id, [entries]) per add_leads call
        self.activated = []

    async def create_campaign(self, payload):
        if self.fail_create:
            raise InstantlyError("bad key")
        self.created = payload
        return "inst-abc"

    async def add_leads(self, instantly_campaign_id, leads):
        if any(e["email"] in self.fail_lead_emails for e in leads):
            raise InstantlyError("lead rejected")
        self.batches.append((instantly_campaign_id, leads))
        self.leads.extend(leads)

    async def activate(self, instantly_campaign_id):
        if self.fail_activate:
            raise InstantlyError("cannot activate")
        self.activated.append(instantly_campaign_id)


async def _campaign(session, *, n_steps=2):
    from app.campaigns.orm import Campaign, CampaignStep

    c = Campaign(
        id=CID, name="Drone OEMs", category_id=1, target_category_id=1,
        geography_id=1, timezone="Asia/Kolkata", send_days="mon,tue,wed,thu,fri",
        send_start_hour=9, send_end_hour=17,
    )
    for i in range(1, n_steps + 1):
        c.steps.append(
            CampaignStep(step_order=i, wait_days=0 if i == 1 else 3,
                         subject=f"S{i} {{first_name}}", body=f"Hi {{first_name}}\n{{icebreaker}}")
        )
    session.add(c)
    await session.commit()
    return c


async def _lead(session, i, *, valid=True, icebreaker="saw your fleet work",
                stage="enriched", email=None, signal=True, email_status="__auto__"):
    """signal=False → no company/title/scrape detail, so the lead can never get
    an icebreaker (no_source) → EXCLUDED from the push, not blocking.
    email_status overrides the verdict (e.g. 'invalid' for terminal/un-sendable)."""
    from app.leads.orm import Company, Lead

    company_id = None
    if signal:
        company = Company(name=f"Co{i}")
        session.add(company)
        await session.flush()
        company_id = company.id
    status = ("valid" if valid else None) if email_status == "__auto__" else email_status
    lead = Lead(
        first_name=f"L{i}", last_name="T",
        title="Ops" if signal else None,
        email=email if email is not None else f"l{i}@co.com",
        icebreaker=icebreaker, campaign_id=CID, company_id=company_id,
        dedup_key=f"nc:push-{i}", stage=stage, source="apify",
        email_status=status,
    )
    session.add(lead)
    await session.commit()
    return lead


async def _reget_campaign(session):
    from app.campaigns.orm import Campaign
    return await session.get(Campaign, CID)


async def test_gate_not_ready_when_a_lead_is_unverified(session):
    await _campaign(session)
    await _lead(session, 1, valid=True)
    await _lead(session, 2, valid=False)  # still un-verified → pending

    st = await push_status(session, await _reget_campaign(session))
    assert st.eligible == 1
    assert st.pending == 1
    assert st.can_push is False
    assert st.reason == "not_ready"


async def test_gate_ready_excludes_no_detail_leads(session):
    await _campaign(session)
    await _lead(session, 1, valid=True, icebreaker="line one")
    # valid but no icebreaker AND no scrape signal → excluded, not blocking.
    await _lead(session, 2, valid=True, icebreaker=None, signal=False)

    st = await push_status(session, await _reget_campaign(session))
    assert st.eligible == 1
    assert st.excluded == 1
    assert st.pending == 0
    assert st.can_push is True
    assert st.reason is None


async def test_terminal_invalid_leads_are_excluded_not_blocking(session):
    await _campaign(session)
    await _lead(session, 1, valid=True, icebreaker="line one")
    # email came back invalid/risky/no_email — can NEVER be sent → excluded.
    await _lead(session, 2, email_status="invalid", icebreaker="x")
    await _lead(session, 3, email_status="risky", icebreaker="x")
    await _lead(session, 4, email_status="no_email", icebreaker="x")

    st = await push_status(session, await _reget_campaign(session))
    assert st.eligible == 1
    assert st.excluded == 3
    assert st.pending == 0
    assert st.can_push is True
    assert st.reason is None


async def test_push_creates_draft_uploads_leads_and_queues_them(session):
    await _campaign(session)
    await _lead(session, 1, stage="enriched")
    await _lead(session, 2, stage="new")
    fake = FakeClient()

    job = await jobs_service.create_job(session, kind="instantly_push", campaign_id=CID)
    await run_push_job(session, job.id, CID, client=fake)

    # campaign created with the app's exact name + sequence
    assert fake.created["name"] == "Drone OEMs"
    assert len(fake.created["sequences"][0]["steps"]) == 2
    assert len(fake.leads) == 2
    assert fake.batches[0][0] == "inst-abc"  # batch carries campaign_id

    # both leads moved FORWARD to queued, with an audit event each
    from sqlalchemy import select
    from app.leads.orm import Lead, LeadEvent
    leads = (await session.execute(select(Lead).where(Lead.campaign_id == CID))).scalars().all()
    assert all(l.stage == "queued" for l in leads)
    events = (await session.execute(
        select(LeadEvent).where(LeadEvent.kind == "stage_change", LeadEvent.to_value == "queued")
    )).scalars().all()
    assert len(events) == 2
    assert all(e.actor_name == "system (Instantly push)" for e in events)

    # job + persisted row
    j = await jobs_service.get_job(session, job.id)
    assert j.status == "done" and j.created_count == 2
    st = await push_status(session, await _reget_campaign(session))
    assert st.state == "draft"
    assert st.instantly_campaign_id == "inst-abc"
    assert st.leads_pushed == 2


async def test_repush_is_locked_after_create(session):
    await _campaign(session)
    await _lead(session, 1)
    fake = FakeClient()
    job1 = await jobs_service.create_job(session, kind="instantly_push", campaign_id=CID)
    await run_push_job(session, job1.id, CID, client=fake)

    st = await push_status(session, await _reget_campaign(session))
    assert st.can_push is False
    assert st.reason == "already_pushed"

    # A second job body refuses to create another Instantly campaign.
    fake2 = FakeClient()
    job2 = await jobs_service.create_job(session, kind="instantly_push", campaign_id=CID)
    await run_push_job(session, job2.id, CID, client=fake2)
    assert fake2.created is None
    j2 = await jobs_service.get_job(session, job2.id)
    assert j2.status == "error"


async def test_failed_create_records_error_and_stays_retryable(session):
    await _campaign(session)
    await _lead(session, 1)
    fake = FakeClient(fail_create=True)
    job = await jobs_service.create_job(session, kind="instantly_push", campaign_id=CID)
    await run_push_job(session, job.id, CID, client=fake)

    j = await jobs_service.get_job(session, job.id)
    assert j.status == "error"
    st = await push_status(session, await _reget_campaign(session))
    # No Instantly id was ever returned → not locked; the gate allows a retry.
    assert st.instantly_campaign_id is None
    assert st.can_push is True


async def test_lead_upload_failure_returns_to_create_not_start(session):
    # A failed push (e.g. Instantly lead-limit) must NOT become a startable draft.
    # It surfaces the error and the page returns to "Create" (can_push) — no Start.
    await _campaign(session)
    await _lead(session, 1, email="good@co.com")
    await _lead(session, 2, email="bad@co.com")
    fake = FakeClient(fail_lead_emails=["bad@co.com"])
    job = await jobs_service.create_job(session, kind="instantly_push", campaign_id=CID)
    await run_push_job(session, job.id, CID, client=fake)

    j = await jobs_service.get_job(session, job.id)
    assert j.created_count == 0 and j.error_count == 2
    assert "lead rejected" in (j.message or "")
    st = await push_status(session, await _reget_campaign(session))
    assert st.state == "error"
    assert st.can_push is True       # back to Create — retryable
    assert st.can_start is False     # Start hidden
    assert st.leads_failed == 2
    assert "lead rejected" in (st.error or "")


async def test_retry_after_failure_reuses_same_draft(session):
    # First attempt creates the campaign but leads fail (quota). Retry must reuse
    # the SAME remote campaign (no duplicate) and succeed once the cause is fixed.
    await _campaign(session)
    await _lead(session, 1, email="x@co.com")
    fail = FakeClient(fail_lead_emails=["x@co.com"])
    job1 = await jobs_service.create_job(session, kind="instantly_push", campaign_id=CID)
    await run_push_job(session, job1.id, CID, client=fail)
    assert fail.created is not None  # campaign was created on attempt 1

    # Retry with a healthy client — quota "freed".
    ok = FakeClient()
    job2 = await jobs_service.create_job(session, kind="instantly_push", campaign_id=CID)
    await run_push_job(session, job2.id, CID, client=ok)
    assert ok.created is None        # REUSED the existing draft — no new campaign
    assert ok.batches[0][0] == "inst-abc"
    st = await push_status(session, await _reget_campaign(session))
    assert st.state == "draft"
    assert st.can_start is True
    assert st.leads_pushed == 1


async def test_start_activates_then_is_idempotent(session):
    await _campaign(session)
    await _lead(session, 1)
    fake = FakeClient()
    job = await jobs_service.create_job(session, kind="instantly_push", campaign_id=CID)
    await run_push_job(session, job.id, CID, client=fake)

    state = await start_campaign(session, await _reget_campaign(session), client=fake)
    assert state.state == "live"
    assert fake.activated == ["inst-abc"]

    # second start is a no-op (still live, no second activate call)
    state2 = await start_campaign(session, await _reget_campaign(session), client=fake)
    assert state2.state == "live"
    assert fake.activated == ["inst-abc"]


async def test_start_before_push_raises(session):
    await _campaign(session)
    await _lead(session, 1)
    fake = FakeClient()
    try:
        await start_campaign(session, await _reget_campaign(session), client=fake)
        assert False, "expected PushError"
    except PushError:
        pass


async def test_start_api_error_sets_error_state(session):
    await _campaign(session)
    await _lead(session, 1)
    fake = FakeClient(fail_activate=True)
    job = await jobs_service.create_job(session, kind="instantly_push", campaign_id=CID)
    await run_push_job(session, job.id, CID, client=fake)

    state = await start_campaign(session, await _reget_campaign(session), client=fake)
    assert state.state == "error"
    assert "cannot activate" in (state.error or "")
