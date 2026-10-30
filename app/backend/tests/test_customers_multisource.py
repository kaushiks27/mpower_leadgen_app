"""S-MS1 multi-source integration tests — the adaptive loop folding the 6 lanes in
ALONGSIDE Google (option-1: Claude's expanded phrases hit every lane every round),
the per-source counts + per-source cap + repeat-Sync dedup (existing domains skipped),
the marketplace name→domain resolve, the Stage-6 contact precedence/off-domain gate,
and the new DB writers. Pure where possible (injected fns); DB tests use the tmp DB.
"""

from __future__ import annotations

import pytest_asyncio

from app.customers import contact_enrich, discovery, lanes, service, webcheck


@pytest_asyncio.fixture
async def session(client):
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


def _serp(*domains):
    return [{"title": d, "url": f"https://{d}/x", "description": "d"} for d in domains]


def _cand(domain, source, phone=None, email=None, name=None):
    return {
        "name": name or domain, "website": f"https://{domain}/", "domain": domain,
        "category": None, "ctype": None, "country": None, "phone": phone, "email": email,
        "source_url": f"https://{domain}/x", "snippet": "", "discovery_source": source,
    }


# ============================ DISCOVERY: lanes in the loop ==================
async def test_lanes_fold_in_and_per_source_counts_sum_to_unique():
    async def search_fn(q):
        return _serp("g1.com", "shared.com")  # google finds g1 + shared

    async def lane_fn(q):
        # own-domain lanes first (maps owns 'shared.com' tie since google already has it)
        return [_cand("m1.com", "maps", phone="111"), _cand("shared.com", "maps", phone="222"),
                _cand("l1.com", "linkedin")]

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=None, categories=["Survey"],
        max_rounds=1, plateau_threshold=2, max_queries_per_round=8,
        lane_fn=lane_fn,
    )
    doms = {c["domain"] for c in out["candidates"]}
    assert doms == {"g1.com", "shared.com", "m1.com", "l1.com"}
    counts = out["source_counts"]
    # google owns g1 + shared (it was first); maps owns m1; linkedin owns l1.
    assert counts == {"google": 2, "maps": 1, "linkedin": 1}
    assert sum(counts.values()) == len(out["candidates"])  # invariant


async def test_shared_domain_fills_blank_phone_from_lane():
    async def search_fn(q):
        return _serp("shared.com")  # google has no phone

    async def lane_fn(q):
        return [_cand("shared.com", "maps", phone="999")]

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=None, categories=["S"],
        max_rounds=1, plateau_threshold=99, max_queries_per_round=4, lane_fn=lane_fn,
    )
    row = next(c for c in out["candidates"] if c["domain"] == "shared.com")
    assert row["discovery_source"] == "google"  # google won identity
    assert row["phone"] == "999"                 # but the lane filled the blank phone


async def test_per_source_cap_limits_each_source():
    async def search_fn(q):
        return _serp("g1.com", "g2.com", "g3.com")

    async def lane_fn(q):
        return [_cand("m1.com", "maps"), _cand("m2.com", "maps"), _cand("m3.com", "maps")]

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=None, categories=["S"],
        max_rounds=1, plateau_threshold=99, max_queries_per_round=4,
        lane_fn=lane_fn, per_source_cap=2,
    )
    assert out["source_counts"] == {"google": 2, "maps": 2}  # capped at 2 each
    assert len(out["candidates"]) == 4


async def test_seen_domains_preseed_skips_known_on_repeat_sync():
    async def search_fn(q):
        return _serp("known.com", "fresh.com")

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=None, categories=["S"],
        max_rounds=1, plateau_threshold=99, max_queries_per_round=4,
        seen_domains={"known.com"},
    )
    doms = {c["domain"] for c in out["candidates"]}
    assert doms == {"fresh.com"}  # the already-known company never re-enters
    assert out["source_counts"] == {"google": 1}


async def test_marketplace_rows_resolved_to_domain_after_loop():
    async def search_fn(q):
        return _serp("g1.com")

    async def lane_fn(q):
        # IndiaMART row: marketplace → no own-domain (domain None), carries a phone.
        c = _cand("ignored", "indiamart", phone="555", name="Enestock")
        c["website"] = None
        c["domain"] = None
        return [c]

    async def resolve_fn(buf):
        # the name→domain resolver fills a real company domain, keeps phone + source
        out = []
        for c in buf:
            r = dict(c)
            r["domain"] = "enestock.com"
            r["website"] = "https://enestock.com/"
            out.append(r)
        return out

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=None, categories=["S"],
        max_rounds=1, plateau_threshold=99, max_queries_per_round=4,
        lane_fn=lane_fn, marketplace_resolve_fn=resolve_fn,
    )
    im = next((c for c in out["candidates"] if c["domain"] == "enestock.com"), None)
    assert im is not None and im["discovery_source"] == "indiamart" and im["phone"] == "555"
    assert out["source_counts"] == {"google": 1, "indiamart": 1}


async def test_lane_failure_never_sinks_discovery():
    async def search_fn(q):
        return _serp("g1.com")

    async def lane_fn(q):
        raise RuntimeError("lane blew up")

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=None, categories=["S"],
        max_rounds=1, plateau_threshold=99, max_queries_per_round=4, lane_fn=lane_fn,
    )
    assert {c["domain"] for c in out["candidates"]} == {"g1.com"}


# ============================ contact_enrich pure mappers ===================
def test_org_phone_extracts_company_phone():
    assert contact_enrich.org_phone({"organization": {"sanitized_phone": "+1-555"}}) == "+1-555"
    assert contact_enrich.org_phone({"organization": {"primary_phone": {"number": "+44 20"}}}) == "+44 20"
    assert contact_enrich.org_phone({}) is None
    assert contact_enrich.org_phone({"organization": "oops"}) is None


def test_pick_person_prefers_has_email():
    people = [{"id": "1", "has_email": False}, {"id": "2", "has_email": True}]
    assert contact_enrich.pick_person(people)["id"] == "2"
    # none with email → first with an id
    assert contact_enrich.pick_person([{"id": "9", "has_email": False}])["id"] == "9"
    assert contact_enrich.pick_person([]) is None
    assert contact_enrich.pick_person([{"no_id": 1}]) is None


def test_match_email_off_domain_gate():
    # on-domain → kept
    m = {"email": "a@garuda.com", "organization": {"primary_domain": "garuda.com"}}
    assert contact_enrich.match_email(m, "garuda.com") == "a@garuda.com"
    # off-domain (person's CURRENT employer differs) → rejected (S1 contamination gate)
    bad = {"email": "a@continental.com", "organization": {"primary_domain": "continental.com"}}
    assert contact_enrich.match_email(bad, "garuda.com") is None
    # no org domain → fall back to the email's own domain
    f = {"email": "x@garuda.com"}
    assert contact_enrich.match_email(f, "https://www.garuda.com/") == "x@garuda.com"
    assert contact_enrich.match_email({}, "garuda.com") is None


def test_map_mv_status():
    assert contact_enrich.map_mv("ok") == "valid"
    assert contact_enrich.map_mv("catch_all") == "catch_all"
    assert contact_enrich.map_mv("invalid") == "invalid"
    assert contact_enrich.map_mv("disposable") == "invalid"
    assert contact_enrich.map_mv(None) == "unknown"


async def test_enrich_contact_blank_without_apollo_key():
    out = await contact_enrich.enrich_contact(None, None, domain="x.com")
    assert out == {"phone": None, "email": None, "email_quality": None}


# ============================ schemeless-URL crash fix ======================
def test_linkedin_bare_domain_gets_scheme():
    """LinkedIn returns bare domains ('www.zxaero.com') — stored schemeless they crash
    the stage-2 httpx resolve. The mapper must store an absolute https URL."""
    c = lanes.map_items("linkedin", [{"name": "Zx", "website": "www.zxaero.com"}])[0]
    assert c["website"] == "https://www.zxaero.com"
    assert c["domain"] == "zxaero.com"


async def test_resolve_website_never_raises_on_schemeless_url():
    """A malformed/schemeless stored website must degrade to unverified, NOT crash the
    whole sync (the '/scoutuav.com.au' ValueError that failed the run)."""
    class _RaisingClient:
        async def get(self, url):
            raise ValueError("unknown url type: '/scoutuav.com.au'")

    patch = await webcheck.resolve_website("/scoutuav.com.au", client=_RaisingClient())
    assert patch["reachable"] is False
    assert patch["website"] == "/scoutuav.com.au"  # row kept, never blanked


# ============================ DB writers: contacts + upsert =================
async def test_upsert_stores_phone_email_source(session):
    await service.upsert_discovered(session, [
        {"name": "Garuda", "website": "https://garuda.com/", "domain": "garuda.com",
         "phone": "111", "email": "Hi@Garuda.com", "discovery_source": "maps"},
    ])
    it = (await service.list_customers(session, include_archived=True))[0]
    assert it.phone == "111" and it.email == "hi@garuda.com" and it.discovery_source == "maps"


async def test_set_contact_precedence_and_off_domain(session):
    await service.upsert_discovered(session, [
        {"name": "G", "website": "https://g.com/", "domain": "g.com", "phone": "native"},
    ])
    it = (await service.list_customers(session, include_archived=True))[0]
    # Apollo phone overwrites native; valid email stored
    await service.set_contact(session, it.id, phone="apollo", email="a@g.com", email_quality="valid")
    r = await service.get_one(session, it.id)
    assert r.phone == "apollo" and r.email == "a@g.com" and r.email_quality == "valid"
    # an invalid verdict NEVER lands an address (flag only, keeps the good email)
    await service.set_contact(session, it.id, phone=None, email="bad@g.com", email_quality="invalid")
    r2 = await service.get_one(session, it.id)
    assert r2.email == "a@g.com"  # unchanged
    assert r2.phone == "apollo"   # blank apollo phone keeps the existing


async def test_customers_to_enrich_eligible_missing_contact_only(session):
    await service.upsert_discovered(session, [
        {"name": "A", "website": "https://a.com/", "domain": "a.com"},
        {"name": "B", "website": "https://b.com/", "domain": "b.com"},
        {"name": "C", "website": "https://c.com/", "domain": "c.com"},
    ])
    rows = await service.list_customers(session, include_archived=True)
    by = {r.name: r for r in rows}
    h = service.content_hash
    # A: Sure, missing contact → target. B: Sure but has phone+email → not. C: Unsure → not.
    await service.apply_band(session, by["A"].id, band="Sure", reason="r", confidence="1",
                             input_hash=h("A", "a.com"))
    await service.apply_band(session, by["B"].id, band="Likely", reason="r", confidence="1",
                             input_hash=h("B", "b.com"))
    await service.set_contact(session, by["B"].id, phone="p", email="e@b.com", email_quality="valid")
    await service.apply_band(session, by["C"].id, band="Unsure", reason="r", confidence="1",
                             input_hash=h("C", "c.com"))
    targets = await service.customers_to_enrich(session)
    assert {t.name for t in targets} == {"A"}


async def test_enrich_attempt_is_idempotent_not_retried(session):
    """A row enriched once (even if nothing found) is stamped email_quality and never
    re-targeted — no perpetual retry, no re-charge."""
    await service.upsert_discovered(session, [
        {"name": "A", "website": "https://a.com/", "domain": "a.com"},
    ])
    a = (await service.list_customers(session, include_archived=True))[0]
    await service.apply_band(session, a.id, band="Sure", reason="r", confidence="1",
                             input_hash=service.content_hash("A", "a.com"))
    assert {t.name for t in await service.customers_to_enrich(session)} == {"A"}
    # attempt finds nothing → stamps "unknown"
    await service.set_contact(session, a.id, phone=None, email=None, email_quality="unknown")
    assert await service.customers_to_enrich(session) == []  # never retried


async def test_customers_to_enrich_limit_caps_batch(session):
    rows = [{"name": f"N{i}", "website": f"https://n{i}.com/", "domain": f"n{i}.com"} for i in range(5)]
    await service.upsert_discovered(session, rows)
    for it in await service.list_customers(session, include_archived=True):
        await service.apply_band(session, it.id, band="Sure", reason="r", confidence="1",
                                 input_hash=service.content_hash(it.name, it.domain))
    assert len(await service.customers_to_enrich(session, limit=2)) == 2
    assert len(await service.customers_to_enrich(session)) == 5


async def test_existing_domains_seed_set(session):
    await service.upsert_discovered(session, [
        {"name": "A", "website": "https://www.A.com/", "domain": "a.com"},
    ])
    known = await service.existing_domains(session)
    assert "a.com" in known


async def test_cancel_is_terminal_and_not_resumable(session):
    """A cancelled job is terminal — never resumed — so the next Sync starts fresh,
    while the partial work already in the DB is preserved (rows untouched)."""
    from app.jobs import service as js

    job = await js.create_job(session, kind="customers_sync", campaign_id=None, message="Q")
    jid = job.id
    assert (await js.latest_resumable(session, campaign_id=None, kind="customers_sync")).id == jid
    await js.mark_cancelled(session, jid, message="Stopped by you.")
    after = await js.get_job(session, jid)
    await session.refresh(after)
    assert after.status == "cancelled" and after.finished_at is not None
    assert await js.latest_resumable(session, campaign_id=None, kind="customers_sync") is None
