"""Generate-Leads staged-worker tests — fakes for ALL network I/O (no credits).

Covers: a fresh run resolves an anchor, discovers across engines, GATES to the
target company, dedups + enriches + verifies, marks done; a SECOND identical run
creates 0 new leads (idempotent); the membership gate drops non-employees and
counts them (KI-26); widen pauses for confirmation then re-discovers on approve;
pause between customers → paused → resume finishes the rest.
"""

from __future__ import annotations

import json

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.jobs import runner as jobs_runner
from app.jobs import service as jobs_service
from app.leadgen import service
from app.leadgen.models import GenerateRequest
from app.leadgen.orm import LeadgenRun
from app.leads.orm import Lead


@pytest_asyncio.fixture
async def session(client):
    import app.db as db_mod

    async with db_mod.async_session() as s:
        from app.settings.keys import _CACHE

        _CACHE["apify"] = "test-apify-key"
        yield s
        _CACHE.pop("apify", None)


async def _seed_customers(session, names):
    from app.customers.orm import CustomerItem

    ids = []
    for i, name in enumerate(names):
        c = CustomerItem(
            name=name, country="India", category="Survey", ctype="OEM",
            scope="local", band="Sure", dedup_key=f"cust-{i}-{name}",
        )
        session.add(c)
        await session.commit()
        await session.refresh(c)
        ids.append(c.id)
    return ids


def _slug(company):
    return company.lower().replace(" ", "").replace(",", "")


async def _anchor(company, country, category):
    """Fake Stage-0 anchor: derive a clean domain/url from the company name."""
    s = _slug(company)
    return {"domain": f"{s}.com", "website": f"https://{s}.com",
            "linkedin_url": f"https://linkedin.com/company/{s}"}


def _person(n, company="DroneCo"):
    return {
        "first_name": f"P{n}", "last_name": "Doe",
        "linkedinUrl": f"https://linkedin.com/in/p{n}",
        "title": "Procurement Manager", "company_name": company, "city": "Pune",
    }


def _engines(fn):
    """Wrap a single ctx→people coroutine as the injected engine list."""
    return [("test", fn)]


async def _matcher(hint):
    # Enrich with an ON-DOMAIN work email (matches the Stage-0 anchor slug.com) so
    # the post-enrich integrity gate keeps the lead. Off-domain is tested separately.
    dom = _slug(hint.get("organization_name") or "example") + ".com"
    return {"email": f"{hint['first_name'].lower()}@{dom}", "phone": "+91 99",
            "headline": "H", "title": "Procurement Manager"}


async def _verifier(email):
    return "valid"


async def _run_to_completion(session, req, **fakes):
    job = await jobs_service.create_job(session, kind=service.JOB_KIND, campaign_id=None)
    states = {str(cid): "pending" for cid in req.customer_ids}
    run = LeadgenRun(
        job_id=job.id,
        params_json=json.dumps(req.model_dump(), sort_keys=True),
        customer_states_json=json.dumps(states, sort_keys=True),
    )
    session.add(run)
    await session.commit()
    await service.run_generate_job(session, job.id, **fakes)
    return job.id


async def test_fresh_run_creates_enriched_leads_and_idempotent(session):
    ids = await _seed_customers(session, ["DroneCo"])
    req = GenerateRequest(customer_ids=ids, role_groups=["Procurement & Sourcing"])

    async def eng_a(ctx):
        return [_person(1, ctx["company"]), _person(2, ctx["company"])]

    async def eng_b(ctx):
        return [_person(2, ctx["company"])]  # dup of person 2 → in-batch dedup

    job_id = await _run_to_completion(
        session, req, anchor=_anchor,
        engines=[("a", eng_a), ("b", eng_b)], widener=None,
        matcher=_matcher, verifier=_verifier,
    )

    import app.db as db_mod
    async with db_mod.async_session() as s2:
        leads = (await s2.execute(select(Lead).where(Lead.source == "leadgen"))).scalars().all()
        assert len(leads) == 2  # person 1 + person 2, dupe collapsed
        for l in leads:
            assert l.email and l.email.endswith("@droneco.com")
            assert l.email_status == "valid"
            assert l.enriched_at is not None
            assert l.stage == "new" and l.campaign_id is None
        j = await jobs_service.get_job(s2, job_id)
        assert j.status == "done" and j.created_count == 2

    job2 = await _run_to_completion(
        session, req, anchor=_anchor,
        engines=[("a", eng_a), ("b", eng_b)], widener=None,
        matcher=_matcher, verifier=_verifier,
    )
    async with db_mod.async_session() as s3:
        leads = (await s3.execute(select(Lead).where(Lead.source == "leadgen"))).scalars().all()
        assert len(leads) == 2  # unchanged
        j2 = await jobs_service.get_job(s3, job2)
        assert j2.status == "done" and j2.created_count == 0


async def test_membership_gate_drops_non_employees(session):
    """KI-26: a person whose employer != the target company is dropped + counted."""
    ids = await _seed_customers(session, ["DSLRPros"])
    req = GenerateRequest(customer_ids=ids, role_groups=["Procurement & Sourcing"])

    async def eng(ctx):
        # One genuine DSLRPros person + one stray from Continental.
        return [_person(1, "DSLRPros"), _person(2, "Continental")]

    job_id = await _run_to_completion(
        session, req, anchor=_anchor, engines=_engines(eng), widener=None,
        matcher=_matcher, verifier=_verifier,
    )
    import app.db as db_mod
    async with db_mod.async_session() as s2:
        leads = (await s2.execute(
            select(Lead).options(selectinload(Lead.company)).where(Lead.source == "leadgen")
        )).scalars().all()
        assert len(leads) == 1
        assert leads[0].company.name == "DSLRPros"  # Continental dropped
        j = await jobs_service.get_job(s2, job_id)
        assert j.status == "done" and j.created_count == 1
        assert "1 excluded" in j.message
        detail = json.loads(j.detail) if j.detail else {}
        assert detail.get("stage_counts", {}).get("excluded") == 1


async def test_post_enrich_offdomain_email_flagged_not_dropped(session):
    """Apollo enrich returns a CURRENT-employer email on a different domain → the
    lead is kept but badged 'off_domain' (SalesPath No), and verify is skipped."""
    ids = await _seed_customers(session, ["DroneCo"])  # anchor → droneco.com
    req = GenerateRequest(customer_ids=ids, role_groups=["Procurement & Sourcing"])

    async def eng(ctx):
        return [_person(1, "DroneCo")]

    async def offdomain_matcher(hint):
        # Person was tagged DroneCo at discovery but Apollo says they're now at OtherCo.
        return {"email": "pat@otherco.ai", "phone": "+1 1", "headline": "H",
                "title": "PM"}

    job_id = await _run_to_completion(
        session, req, anchor=_anchor, engines=_engines(eng), widener=None,
        matcher=offdomain_matcher, verifier=_verifier,
    )
    import app.db as db_mod
    async with db_mod.async_session() as s2:
        leads = (await s2.execute(
            select(Lead).where(Lead.source == "leadgen")
        )).scalars().all()
        assert len(leads) == 1
        lead = leads[0]
        assert lead.archived is False           # kept, not dropped
        assert lead.email == "pat@otherco.ai"  # foreign email retained for context
        assert lead.email_status == "off_domain"  # SalesPath No
        assert lead.enriched_at is not None


async def test_post_enrich_cross_tier_duplicate_email_archived(session):
    """Two records for the same person — one with a LinkedIn URL (li: dedup tier),
    one without — converge on the same enriched email and must collapse to one."""
    ids = await _seed_customers(session, ["DroneCo"])
    req = GenerateRequest(customer_ids=ids, role_groups=["Procurement & Sourcing"])

    async def eng(ctx):
        a = _person(1, "DroneCo")                       # has linkedinUrl → li: key
        b = _person(1, "DroneCo")
        b["linkedinUrl"] = ""                            # no LinkedIn → em:/nc: key
        b["first_name"] = "P1"; b["last_name"] = "Twin"  # different name+li → both created
        return [a, b]

    async def same_email_matcher(hint):
        return {"email": "p1@droneco.com", "phone": "+1 1", "headline": "H", "title": "PM"}

    job_id = await _run_to_completion(
        session, req, anchor=_anchor, engines=_engines(eng), widener=None,
        matcher=same_email_matcher, verifier=_verifier,
    )
    import app.db as db_mod
    async with db_mod.async_session() as s2:
        active = (await s2.execute(
            select(Lead).where(Lead.source == "leadgen", Lead.archived.is_(False))
        )).scalars().all()
        assert len(active) == 1                          # redundant copy archived
        assert active[0].email == "p1@droneco.com"
        assert active[0].email_status == "valid"


async def _build_run(session, ids, req):
    job = await jobs_service.create_job(session, kind=service.JOB_KIND, campaign_id=None)
    states = {str(cid): "pending" for cid in ids}
    run = LeadgenRun(
        job_id=job.id,
        params_json=json.dumps(req.model_dump(), sort_keys=True),
        customer_states_json=json.dumps(states, sort_keys=True),
    )
    session.add(run)
    await session.commit()
    return job.id


async def test_widen_pauses_for_confirmation_then_approve_resumes(session):
    """Thin discovery + Claude available → PAUSE for the user, no auto-widen.

    Approving records the decision, resumes, and the widened re-discovery ingests
    the extra person."""
    ids = await _seed_customers(session, ["ThinCo"])
    req = GenerateRequest(customer_ids=ids, role_groups=["Quality"])
    calls = {"widen": 0}

    async def eng(ctx):
        if "Senior Quality Lead" in ctx["titles"]:  # the widened re-run
            return [_person(9, ctx["company"])]
        return [_person(1, ctx["company"])]  # 1 hit < WIDEN_THRESHOLD

    async def widener(earlier_input):
        calls["widen"] += 1
        assert isinstance(earlier_input, dict) and "currentJobTitles" in earlier_input
        return ["Senior Quality Lead"]

    job_id = await _build_run(session, ids, req)
    await service.run_generate_job(
        session, job_id, anchor=_anchor, engines=_engines(eng), widener=widener,
        matcher=_matcher, verifier=_verifier,
    )

    import app.db as db_mod
    async with db_mod.async_session() as s2:
        j = await jobs_service.get_job(s2, job_id)
        assert j.status == "paused"
        detail = json.loads(j.detail)
        assert detail["awaiting_widen"] is True and detail["awaiting_cid"] == ids[0]
        leads = (await s2.execute(select(Lead).where(Lead.source == "leadgen"))).scalars().all()
        assert leads == []
    assert calls["widen"] == 0  # Claude NOT called until the user approves

    cid = await service.set_widen_decision(session, job_id, approve=True)
    assert cid == ids[0]
    jobs_runner.clear_pause(job_id)
    async with db_mod.async_session() as s3:
        await service.run_generate_job(
            s3, job_id, anchor=_anchor, engines=_engines(eng), widener=widener,
            matcher=_matcher, verifier=_verifier,
        )
        j = await jobs_service.get_job(s3, job_id)
        assert j.status == "done"
        leads = (await s3.execute(select(Lead).where(Lead.source == "leadgen"))).scalars().all()
        assert len(leads) == 2  # thin person 1 + widened person 9
    assert calls["widen"] == 1


async def test_widen_skip_decision_proceeds_with_thin_results(session):
    ids = await _seed_customers(session, ["SkipCo"])
    req = GenerateRequest(customer_ids=ids, role_groups=["Quality"])
    calls = {"widen": 0}

    async def eng(ctx):
        return [_person(1, ctx["company"])]  # always thin

    async def widener(earlier_input):
        calls["widen"] += 1
        return ["X"]

    job_id = await _build_run(session, ids, req)
    await service.run_generate_job(
        session, job_id, anchor=_anchor, engines=_engines(eng), widener=widener,
        matcher=_matcher, verifier=_verifier,
    )
    import app.db as db_mod
    async with db_mod.async_session() as s2:
        assert (await jobs_service.get_job(s2, job_id)).status == "paused"

    await service.set_widen_decision(session, job_id, approve=False)
    jobs_runner.clear_pause(job_id)
    async with db_mod.async_session() as s3:
        await service.run_generate_job(
            s3, job_id, anchor=_anchor, engines=_engines(eng), widener=widener,
            matcher=_matcher, verifier=_verifier,
        )
        j = await jobs_service.get_job(s3, job_id)
        assert j.status == "done"
        leads = (await s3.execute(select(Lead).where(Lead.source == "leadgen"))).scalars().all()
        assert len(leads) == 1
    assert calls["widen"] == 0


async def test_widen_not_offered_above_threshold(session):
    ids = await _seed_customers(session, ["BigCo"])
    req = GenerateRequest(customer_ids=ids, role_groups=["Executive & Founder"])
    calls = {"widen": 0}

    async def eng(ctx):
        return [_person(i, ctx["company"]) for i in range(5)]  # 5 >= threshold

    async def widener(earlier_input):
        calls["widen"] += 1
        return ["X"]

    job_id = await _build_run(session, ids, req)
    await service.run_generate_job(
        session, job_id, anchor=_anchor, engines=_engines(eng), widener=widener,
        matcher=_matcher, verifier=_verifier,
    )
    import app.db as db_mod
    async with db_mod.async_session() as s2:
        assert (await jobs_service.get_job(s2, job_id)).status == "done"
    assert calls["widen"] == 0


async def test_cancel_marks_done_and_next_run_is_fresh(session):
    """Cancelling mid-run marks the job done (non-resumable); a later run is new."""
    ids = await _seed_customers(session, ["AlphaCo", "BetaCo"])
    req = GenerateRequest(customer_ids=ids, role_groups=["Quality"])
    _job = {"id": None}

    async def eng(ctx):
        if ctx["company"] == "AlphaCo":
            jobs_runner.request_cancel(_job["id"])  # user clicks Cancel after #1
        return [_person(abs(hash(ctx["company"])) % 1000, ctx["company"])]

    job = await jobs_service.create_job(session, kind=service.JOB_KIND, campaign_id=None)
    _job["id"] = job.id
    states = {str(cid): "pending" for cid in ids}
    run = LeadgenRun(
        job_id=job.id,
        params_json=json.dumps(req.model_dump(), sort_keys=True),
        customer_states_json=json.dumps(states, sort_keys=True),
    )
    session.add(run)
    await session.commit()
    await service.run_generate_job(
        session, job.id, anchor=_anchor, engines=_engines(eng), widener=None,
        matcher=_matcher, verifier=_verifier,
    )

    import app.db as db_mod
    async with db_mod.async_session() as s2:
        j = await jobs_service.get_job(s2, job.id)
        assert j.status == "done" and "cancelled" in (j.message or "").lower()
        # Cancelled job is NOT resumable → a fresh run gets a brand-new job id.
        resumable = await jobs_service.latest_resumable(s2, campaign_id=None, kind=service.JOB_KIND)
        assert resumable is None
    assert not jobs_runner.is_cancelled(job.id)  # flag cleared by the worker


async def test_cancel_run_endpoint_kills_paused_run(session):
    """cancel_run on a paused/orphaned job marks it done so the next run is fresh."""
    ids = await _seed_customers(session, ["GammaCo"])
    req = GenerateRequest(customer_ids=ids, role_groups=["Quality"])
    job_id = await _build_run(session, ids, req)
    await jobs_service.mark_paused(session, job_id, message="paused")

    cancelled = await service.cancel_run(session, runner=jobs_runner)
    assert cancelled == job_id
    import app.db as db_mod
    async with db_mod.async_session() as s2:
        j = await jobs_service.get_job(s2, job_id)
        assert j.status == "done"
        assert await jobs_service.latest_resumable(s2, campaign_id=None, kind=service.JOB_KIND) is None
    jobs_runner.clear_cancel(job_id)


async def test_pause_between_customers_then_resume(session):
    ids = await _seed_customers(session, ["AlphaCo", "BetaCo"])
    req = GenerateRequest(customer_ids=ids, role_groups=["Quality"])
    _pause_job = {"id": None}

    async def eng(ctx):
        if ctx["company"] == "AlphaCo":
            jobs_runner.request_pause(_pause_job["id"])
        return [_person(abs(hash(ctx["company"])) % 1000, ctx["company"])]

    job = await jobs_service.create_job(session, kind=service.JOB_KIND, campaign_id=None)
    _pause_job["id"] = job.id
    states = {str(cid): "pending" for cid in ids}
    run = LeadgenRun(
        job_id=job.id,
        params_json=json.dumps(req.model_dump(), sort_keys=True),
        customer_states_json=json.dumps(states, sort_keys=True),
    )
    session.add(run)
    await session.commit()

    await service.run_generate_job(
        session, job.id, anchor=_anchor, engines=_engines(eng), widener=None,
        matcher=_matcher, verifier=_verifier,
    )

    import app.db as db_mod
    async with db_mod.async_session() as s2:
        j = await jobs_service.get_job(s2, job.id)
        assert j.status == "paused"
        r = (await s2.execute(select(LeadgenRun).where(LeadgenRun.job_id == job.id))).scalars().first()
        st = json.loads(r.customer_states_json)
        assert list(st.values()).count("done") == 1
        assert list(st.values()).count("pending") == 1
        leads_after = (await s2.execute(select(Lead).where(Lead.source == "leadgen"))).scalars().all()
        assert len(leads_after) == 1

    jobs_runner.clear_pause(job.id)
    async with db_mod.async_session() as s3:
        await service.run_generate_job(
            s3, job.id, anchor=_anchor, engines=_engines(eng), widener=None,
            matcher=_matcher, verifier=_verifier,
        )
        j = await jobs_service.get_job(s3, job.id)
        assert j.status == "done"
        leads = (await s3.execute(select(Lead).where(Lead.source == "leadgen"))).scalars().all()
        assert len(leads) == 2
