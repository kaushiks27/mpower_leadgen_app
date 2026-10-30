"""S-CR2 — Competitors parity tests: multi-source discovery loop (Google + 6 lanes),
per-source counts/cap, repeat-Sync dedup (next-N-new), marketplace name→domain resolve,
sharper battery-MAKER competitor queries (critical-1, not drone OEMs), the stronger
Selling-to crawler input (critical-2), the discovery_source writer, and cancel-is-terminal
(Stop parity). Pure where possible (injected fns); DB tests use the tmp DB.
"""

from __future__ import annotations

import pytest_asyncio

from app.competitors import apify_client, config, discovery, lanes, service, sourcing, webcheck


@pytest_asyncio.fixture
async def session(client):
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


def _serp(*domains):
    return [{"title": d, "url": f"https://{d}/x", "description": "d"} for d in domains]


def _cand(domain, source, phone=None, name=None):
    return {
        "name": name or domain, "website": f"https://{domain}/", "domain": domain,
        "category": None, "ctype": None, "country": None, "phone": phone, "email": None,
        "source_url": f"https://{domain}/x", "snippet": "", "discovery_source": source,
    }


# ============================ DISCOVERY: lanes in the loop ==================
async def test_lanes_fold_in_and_per_source_counts_sum_to_unique():
    async def search_fn(q):
        return _serp("g1.com", "shared.com")

    async def lane_fn(q):
        return [_cand("m1.com", "maps"), _cand("shared.com", "maps"), _cand("l1.com", "linkedin")]

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=None, categories=["Survey"],
        max_rounds=1, plateau_threshold=2, max_queries_per_round=8, lane_fn=lane_fn,
    )
    doms = {c["domain"] for c in out["candidates"]}
    assert doms == {"g1.com", "shared.com", "m1.com", "l1.com"}
    counts = out["source_counts"]
    assert counts == {"google": 2, "maps": 1, "linkedin": 1}
    assert sum(counts.values()) == len(out["candidates"])  # invariant


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
    assert out["source_counts"] == {"google": 2, "maps": 2}
    assert len(out["candidates"]) == 4


async def test_seen_domains_preseed_skips_known_on_repeat_sync():
    async def search_fn(q):
        return _serp("known.com", "fresh.com")

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=None, categories=["S"],
        max_rounds=1, plateau_threshold=99, max_queries_per_round=4,
        seen_domains={"known.com"},
    )
    assert {c["domain"] for c in out["candidates"]} == {"fresh.com"}
    assert out["source_counts"] == {"google": 1}


async def test_marketplace_rows_resolved_to_domain_after_loop():
    async def search_fn(q):
        return _serp("g1.com")

    async def lane_fn(q):
        c = _cand("ignored", "indiamart", phone="555", name="Enestock")
        c["website"] = None
        c["domain"] = None
        return [c]

    async def resolve_fn(buf):
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


# ============================ critical-1: sharper competitor queries =========
def test_category_competitor_queries_target_battery_makers_not_oems():
    qs = sourcing.category_competitor_queries("Surveillance")
    blob = " ".join(qs).lower()
    assert len(qs) >= 3                                   # multi-angle, not one generic query
    assert all("drone" in q.lower() for q in qs)         # drone-anchored (on-domain)
    assert "battery pack manufacturer" in blob           # battery MAKER, not a drone OEM
    assert qs[0] == sourcing._category_term("Surveillance")  # primary leads (attribution key)
    # an operational / non-segment category issues NO competitor query
    assert sourcing.category_competitor_queries("Recycling") == []


def test_category_query_map_attributes_every_angle():
    cats = ["Surveillance"]
    m = sourcing.category_query_map(cats)
    for q in sourcing.category_competitor_queries("Surveillance"):
        assert m[q] == "Surveillance"


def test_marketplace_resolve_query_competitor_anchored():
    qs = sourcing.marketplace_resolve_query("Enestock")
    assert qs and "enestock" in qs[0].lower() and "drone battery" in qs[0].lower()
    assert sourcing.marketplace_resolve_query("") == []


def test_selling_to_query_covers_trusted_partner_phrasing():
    blob = " ".join(sourcing.profile_queries("Grepow", "grepow.com")).lower()
    assert "our customers" in blob and "trusted" in blob   # user tip phrasing
    assert "case studies" in blob or "clients" in blob


# ============================ critical-2: stronger crawler ===================
def test_crawl_input_uses_js_crawler_and_evidence_globs():
    inp = apify_client.crawl_input("https://grepow.com/", max_pages=6)
    assert inp["crawlerType"] == config.CRAWLER_TYPE
    assert config.CRAWLER_TYPE.startswith("playwright")  # JS-rendering, not raw cheerio
    assert inp["removeCookieWarnings"] is True
    globs = " ".join(g["glob"] for g in inp["includeUrlGlobs"]).lower()
    assert "customer" in globs and "partner" in globs and "trusted" in globs
    assert all("grepow.com" in g["glob"] for g in inp["includeUrlGlobs"])  # scoped to the site


# ============================ DB writers + provenance =======================
async def test_upsert_stores_discovery_source(session):
    await service.upsert_discovered(session, [
        {"name": "Grepow", "website": "https://grepow.com/", "domain": "grepow.com",
         "phone": "111", "email": "x@grepow.com", "discovery_source": "maps"},
    ])
    it = (await service.list_competitors(session, include_archived=True))[0]
    assert it.discovery_source == "maps"  # phone/email keys harmlessly ignored (no columns)


async def test_existing_domains_seed_set(session):
    await service.upsert_discovered(session, [
        {"name": "A", "website": "https://www.A.com/", "domain": "a.com", "discovery_source": "google"},
    ])
    assert "a.com" in await service.existing_domains(session)


async def test_resolve_website_never_raises_on_schemeless_url():
    class _RaisingClient:
        async def get(self, url):
            raise ValueError("unknown url type")

    patch = await webcheck.resolve_website("/badurl.com", client=_RaisingClient())
    assert patch["reachable"] is False and patch["website"] == "/badurl.com"


def test_linkedin_bare_domain_gets_scheme():
    c = lanes.map_items("linkedin", [{"name": "Zx", "website": "www.zxaero.com"}])[0]
    assert c["website"] == "https://www.zxaero.com" and c["domain"] == "zxaero.com"


# ============================ Stop parity ===================================
async def test_cancel_is_terminal_and_not_resumable(session):
    """Stop = a cancelled job is terminal (never resumed) so the next Sync starts fresh,
    while partial work already in the DB is preserved."""
    from app.jobs import service as js

    job = await js.create_job(session, kind="competitors_sync", campaign_id=None, message="Q")
    jid = job.id
    assert (await js.latest_resumable(session, campaign_id=None, kind="competitors_sync")).id == jid
    await js.mark_cancelled(session, jid, message="Stopped by you.")
    after = await js.get_job(session, jid)
    await session.refresh(after)
    assert after.status == "cancelled" and after.finished_at is not None
    assert await js.latest_resumable(session, campaign_id=None, kind="competitors_sync") is None
