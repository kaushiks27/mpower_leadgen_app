"""mPower's Brain — Competitors module tests (deterministic, no network/spend).

Covers the load-bearing invariants: dedup determinism (by domain), idempotent
upsert, manual-row protection, per-field human-override locks, scope derivation
(Local=India / Global), robust Claude-classifier parsing (never silently Sure;
category snapped to the canonical set, never invented), the adaptive discovery
loop (dedup + plateau stop + candidate cap + seed fallback), the blocklist, and
the admin-only API gate.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from conftest import login, make_user

from app.competitors import claude_classify, discovery, service, sourcing, webcheck


@pytest_asyncio.fixture
async def session(client):
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


# --- normalization, keys, scope ---------------------------------------------
def test_normalize_domain():
    assert service.normalize_domain("https://www.Grepow.com/uav") == "grepow.com"
    assert service.normalize_domain("herewinpower.com") == "herewinpower.com"
    assert service.normalize_domain(None) == ""


def test_dedup_key_by_domain_deterministic():
    a = service.dedup_key_synced("https://www.grepow.com/x")
    b = service.dedup_key_synced("grepow.com")
    assert a == b  # same registrable host → same key


def test_manual_key_never_collides_with_synced():
    assert service.dedup_key_manual("Grepow") != service.dedup_key_synced("grepow.com")


def test_derive_scope_india_is_local():
    assert service.derive_scope("India") == "local"
    assert service.derive_scope("in") == "local"
    assert service.derive_scope("China") == "global"
    assert service.derive_scope(None) == "global"


def test_content_hash_changes_with_domain_not_name():
    # domain is the stable identity → different domains differ
    assert service.content_hash("Grepow", "grepow.com") != service.content_hash("Grepow", "xt.com")
    # name change must NOT change the hash (classifier corrects the name; idempotency)
    assert service.content_hash("Grepow", "grepow.com") == service.content_hash("Best Drone Batteries 2026", "grepow.com")


# --- idempotent upsert + manual protection + field locks --------------------
def _rows():
    return [
        {"name": "Grepow", "website": "https://grepow.com/", "domain": "grepow.com",
         "country": "China", "source_url": "u1"},
        {"name": "Herewin", "website": "https://herewinpower.com/", "domain": "herewinpower.com",
         "country": None, "source_url": "u2"},
    ]


async def test_upsert_idempotent(session):
    i1, u1, s1 = await service.upsert_discovered(session, _rows())
    assert (i1, u1, s1) == (2, 0, 0)
    i2, u2, s2 = await service.upsert_discovered(session, _rows())
    assert (i2, u2, s2) == (0, 2, 0)  # 0 new, both refreshed
    assert len(await service.list_competitors(session, include_archived=True)) == 2


async def test_upsert_skips_rows_without_domain(session):
    inserted, _, _ = await service.upsert_discovered(
        session, [{"name": "NoSite", "website": None, "domain": None}]
    )
    assert inserted == 0


async def test_sync_never_overwrites_manual_row(session):
    manual = await service.add_manual(
        session, name="Grepow", website="https://grepow.com/",
        country="China", category=None, selling_to=None,
    )
    assert manual.manual is True and manual.band == "Sure"
    # a discovered row for the SAME domain must be skipped (manual protected)
    i, u, skipped = await service.upsert_discovered(session, [
        {"name": "Grepow Inc", "website": "https://grepow.com/", "domain": "grepow.com"},
    ])
    assert skipped == 1 and i == 0
    rows = await service.list_competitors(session, include_archived=True)
    assert len(rows) == 1 and rows[0].name == "Grepow"


async def test_manual_duplicate_rejected(session):
    await service.add_manual(session, name="Dup", website=None, country=None,
                             category=None, selling_to=None)
    with pytest.raises(ValueError):
        await service.add_manual(session, name="Dup", website=None, country=None,
                                 category=None, selling_to=None)


async def test_manual_add_locks_provided_fields(session):
    m = await service.add_manual(session, name="X", website="https://x.com/",
                                 country="India", category="Survey", selling_to="ACME")
    out = service.to_out(m)
    assert m.scope == "local"  # India → local
    assert set(out.locked_fields) == {"name", "website", "country", "category", "selling_to"}


async def test_edit_locks_field_and_survives_classification(session):
    await service.upsert_discovered(session, _rows())
    item = (await service.list_competitors(session, include_archived=True))[0]
    # user fixes the country → that field locks
    await service.edit_competitor(session, item.id, country="China")
    fresh = await service.get_one(session, item.id)
    assert "country" in (fresh.locked_fields or "")
    # a later classification proposing a DIFFERENT country must NOT overwrite it
    await service.apply_classification(
        session, item.id, band="Sure", reason="r", confidence="0.9",
        input_hash="h", country="Germany", category=None, selling_to=None,
    )
    again = await service.get_one(session, item.id)
    assert again.country == "China" and again.band == "Sure"


async def test_apply_classification_sets_scope_and_category(session):
    await service.upsert_discovered(session, [
        {"name": "Artek", "website": "https://artekgroup.in/", "domain": "artekgroup.in"},
    ])
    item = (await service.list_competitors(session, include_archived=True))[0]
    await service.apply_classification(
        session, item.id, band="Sure", reason="india maker", confidence="0.95",
        input_hash="h", country="India", category="Survey", selling_to="Farm Co",
    )
    again = await service.get_one(session, item.id)
    assert again.scope == "local" and again.category == "Survey"
    assert again.selling_to == "Farm Co" and again.band == "Sure"


async def test_classification_empty_customers_sets_note(session):
    await service.upsert_discovered(session, [
        {"name": "Q", "website": "https://q.com/", "domain": "q.com"},
    ])
    item = (await service.list_competitors(session, include_archived=True))[0]
    await service.apply_classification(
        session, item.id, band="Likely", reason="r", confidence="0.6",
        input_hash="h", selling_to=None, selling_to_note="no public data",
    )
    again = await service.get_one(session, item.id)
    assert again.selling_to is None and again.selling_to_note == "no public data"


# --- robust classifier parsing (never silently Sure; category never invented) -
def test_parse_valid_verdict():
    v = claude_classify.parse_classification(
        '{"band":"Sure","reason":"maker","confidence":0.9,"country":"China",'
        '"category":"Survey","selling_to":["DJI","Autel"]}',
        ["Survey", "Agriculture Spraying"],
    )
    assert v["band"] == "Sure" and v["confidence"] == "0.9"
    assert v["country"] == "China" and v["category"] == "Survey"
    assert v["selling_to"] == "DJI, Autel"


def test_parse_junk_falls_back_to_unsure():
    v = claude_classify.parse_classification("not json", ["Survey"])
    assert v["band"] == "Unsure" and "unscored" in v["reason"]
    assert v["selling_to"] is None and v["selling_to_note"]


def test_parse_invalid_band_falls_back_to_unsure():
    v = claude_classify.parse_classification(
        '{"band":"Maybe","reason":"x","confidence":1}', ["Survey"]
    )
    assert v["band"] == "Unsure"  # never silently Sure


def test_category_snaps_to_canonical():
    cats = ["Agriculture Spraying drone batteries", "Surveillance drone batteries"]
    # exact (case-insensitive)
    v = claude_classify.parse_classification(
        '{"band":"Sure","reason":"r","confidence":1,"category":"agriculture spraying drone batteries"}', cats
    )
    assert v["category"] == "Agriculture Spraying drone batteries"
    # substring match
    v2 = claude_classify.parse_classification(
        '{"band":"Sure","reason":"r","confidence":1,"category":"Surveillance"}', cats
    )
    assert v2["category"] == "Surveillance drone batteries"


def test_category_unrecognized_is_blank_not_guessed():
    v = claude_classify.parse_classification(
        '{"band":"Sure","reason":"r","confidence":1,"category":"Quantum Reactors"}',
        ["Survey", "Delivery"],
    )
    assert v["category"] is None


def test_empty_customers_list_becomes_note():
    v = claude_classify.parse_classification(
        '{"band":"No","reason":"oem","confidence":0.8,"selling_to":[]}', ["Survey"]
    )
    assert v["selling_to"] is None and "No public customer data" in v["selling_to_note"]


def test_propose_queries_parse():
    qs = claude_classify.parse_queries('{"queries":["a maker","b supplier"," "]}')
    assert qs == ["a maker", "b supplier"]
    assert claude_classify.parse_queries("junk") == []


# --- discovery loop (dedup + plateau + cap + seed fallback) ------------------
def _serp(domains):
    return [{"title": d.split(".")[0], "url": f"https://{d}/x", "description": "d"} for d in domains]


def test_profile_queries_are_solid():
    qs = sourcing.profile_queries("Grepow", "grepow.com")
    blob = " ".join(qs).lower()
    assert any("grepow.com" in q for q in qs)        # site identity anchored on domain
    assert "grepow" in blob                          # name anchored
    assert "manufacturer" in blob                    # is-it-a-maker signal
    assert "headquarters" in blob or "country" in blob  # country signal
    assert "customers" in blob or "clients" in blob  # selling-to signal
    assert "volza.com" in blob                        # trade-record source


def test_evidence_text_puts_search_first_and_survives_empty_crawl():
    # Danenergy failure mode: crawl is empty (cookie wall) but search has signal.
    search = [{"title": "Danenergy", "description": "manufactures drone battery packs", "url": "x"}]
    out = sourcing.evidence_text([], search)
    assert "[search]" in out and "drone battery packs" in out
    # search appears before any site block when both present
    both = sourcing.evidence_text([{"url": "u", "markdown": "site body"}], search)
    assert both.index("[search]") < both.index("[site:")


async def test_extract_candidates_blocklist_and_dedupe():
    rows = _serp(["grepow.com", "grepow.com", "alibaba.com", "youtube.com", "herewinpower.com"])
    cands = sourcing.extract_candidates(rows)
    doms = {c["domain"] for c in cands}
    assert doms == {"grepow.com", "herewinpower.com"}  # dirs/social dropped, dupes merged


async def test_discovery_dedup_and_plateau_stop():
    rounds_seen = []

    async def search_fn(queries):
        # round 0 finds 3 new; round 1 finds the same 3 (0 new) → plateau stop
        if not rounds_seen:
            rounds_seen.append(1)
            return _serp(["a.com", "b.com", "c.com"])
        rounds_seen.append(1)
        return _serp(["a.com", "b.com", "c.com"])

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=None, categories=["Survey"],
        max_rounds=5, plateau_threshold=2, max_queries_per_round=8,
    )
    assert len(out["candidates"]) == 3
    assert out["rounds"] == 2  # stopped on the plateau round


async def test_discovery_candidate_cap():
    async def search_fn(queries):
        return _serp([f"c{i}.com" for i in range(10)])

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=None, categories=["Survey"],
        max_rounds=5, plateau_threshold=1, max_queries_per_round=8, max_candidates=4,
    )
    assert len(out["candidates"]) == 4


async def test_discovery_falls_back_to_seed_when_propose_empty():
    captured = {}

    async def search_fn(queries):
        captured["q"] = queries
        return _serp(["a.com"])

    async def propose_fn(cats, r, seen):
        return []  # propose nothing → must use deterministic seeds

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=propose_fn, categories=["Agriculture Spraying"],
        max_rounds=1, plateau_threshold=2, max_queries_per_round=20,
    )
    assert out["candidates"] and captured["q"]  # seed queries were issued
    assert any("manufacturer" in q for q in captured["q"])


# --- live category sync (data dependency on the brain catalog) ---------------
async def test_mpower_categories_reads_brain_catalog(session):
    from app.brain import service as brain_service

    await brain_service.upsert_synced(session, [
        {"kind": "product", "name": "P1", "handle": "p1", "category": "Surveillance",
         "price_inr": "1", "source_url": "u"},
        {"kind": "product", "name": "P2", "handle": "p2", "category": "Delivery",
         "price_inr": "2", "source_url": "u"},
    ])
    cats = await service.mpower_categories(session)
    assert "Surveillance" in cats and "Delivery" in cats


# --- admin-only API gate -----------------------------------------------------
async def test_list_requires_admin(client):
    await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "rep@buloop.com", "password123")
    assert (await client.get("/api/brain/competitors")).status_code == 403


async def test_list_unauthed_401(client):
    assert (await client.get("/api/brain/competitors")).status_code == 401


async def test_admin_can_add_and_list(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    res = await client.post(
        "/api/brain/competitors",
        json={"name": "Grepow", "website": "https://grepow.com/", "country": "China",
              "category": "Survey", "selling_to": "DJI"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["manual"] is True and body["band"] == "Sure" and body["scope"] == "global"
    listing = (await client.get("/api/brain/competitors")).json()
    assert any(i["name"] == "Grepow" for i in listing)


async def test_sync_route_rep_forbidden(client):
    await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "rep@buloop.com", "password123")
    assert (await client.post("/api/brain/competitors/sync", json={})).status_code == 403


async def test_dev_info_exposes_real_prompt(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    info = (await client.get("/api/brain/competitors/dev-info")).json()
    assert "SalesPath Sure" in info["claude_system"]
    assert info["search_actor"] == "apify~google-search-scraper"
    assert "{name}" in info["claude_user_template"]
    assert any("import/export" in s or "trade" in s for s in info["selling_to_sources"])
    # the line-by-line enrichment pass is exposed for review/lock-down
    assert info["enrichment_queries"] and any("manufacturer" in q for q in info["enrichment_queries"])


async def test_active_sync_none_when_idle(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    body = (await client.get("/api/brain/competitors/active-sync")).json()
    assert body["job"] is None


# --- pause / resume ----------------------------------------------------------
def test_pause_registry():
    from app.jobs import runner
    runner.clear_pause(999)
    assert runner.is_paused(999) is False
    runner.request_pause(999)
    assert runner.is_paused(999) is True
    runner.clear_pause(999)
    assert runner.is_paused(999) is False


async def test_mark_paused_sets_resumable_status(session):
    from app.jobs import service as jobs_service
    job = await jobs_service.create_job(session, kind="competitors_sync", campaign_id=None)
    await jobs_service.mark_paused(session, job.id, message="Paused (3/10).")
    fresh = await jobs_service.get_job(session, job.id)
    assert fresh.status == "paused" and fresh.finished_at is None  # resumable
    # active_job ignores paused (so Resume starts a fresh continuing run)…
    assert await jobs_service.active_job(session, campaign_id=None, kind="competitors_sync") is None
    # …but latest_resumable surfaces it (so the popup reattaches + offers Resume)
    res = await jobs_service.latest_resumable(session, campaign_id=None, kind="competitors_sync")
    assert res is not None and res.id == job.id


async def test_active_sync_surfaces_paused_job(client):
    import app.db as db_mod
    from app.jobs import service as jobs_service
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    async with db_mod.async_session() as s:
        job = await jobs_service.create_job(s, kind="competitors_sync", campaign_id=None)
        await jobs_service.mark_paused(s, job.id, message="Paused.")
    body = (await client.get("/api/brain/competitors/active-sync")).json()
    assert body["job"] and body["job"]["status"] == "paused"


async def test_pause_endpoint_admin_only(client):
    await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "rep@buloop.com", "password123")
    assert (await client.post("/api/brain/competitors/sync/pause", json={})).status_code == 403


async def test_resume_reuses_paused_job_not_a_new_discovery(client):
    """The fix: POST /sync with a PAUSED job RESUMES it (same job id) instead of
    launching a fresh job that re-runs stage-1 discovery from scratch."""
    import app.db as db_mod
    from sqlalchemy import func, select
    from app.jobs import service as jobs_service
    from app.jobs.orm import Job

    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    async with db_mod.async_session() as s:
        job = await jobs_service.create_job(s, kind="competitors_sync", campaign_id=None)
        await jobs_service.mark_paused(s, job.id, message="Paused (12/463).")
        paused_id = job.id

    res = await client.post("/api/brain/competitors/sync", json={})
    assert res.status_code == 200 and res.json()["id"] == paused_id  # resumed, same job
    async with db_mod.async_session() as s:
        n = await s.scalar(
            select(func.count()).select_from(Job).where(Job.kind == "competitors_sync")
        )
    assert n == 1  # no fresh discovery job created


# --- category-first pipeline: originating-search category attribution --------
def test_category_query_map_maps_query_to_category():
    cats = ["Surveillance drone batteries", "Delivery drone batteries"]
    m = sourcing.category_query_map(cats)
    # drone-anchored, battery-stripped segment + maker tail (off-domain bare-label fix)
    assert m[sourcing._category_term("Surveillance drone batteries")] == "Surveillance drone batteries"
    assert m[sourcing._category_term("Delivery drone batteries")] == "Delivery drone batteries"


def test_bare_category_is_drone_anchored_not_off_domain():
    # the bug: "Mapping" -> "Mapping manufacturer" (Google Maps). Fixed: drone-anchored.
    q = sourcing._category_term("Mapping")
    assert "drone" in q.lower() and "battery" in q.lower()
    # a non-segment / operational category issues NO per-category query
    assert sourcing._category_term("Recycling") is None
    assert "Recycling manufacturer" not in sourcing.seed_queries(["Recycling"], 0)


def test_extract_candidates_attributes_originating_category():
    cats = ["Surveillance drone batteries"]
    cmap = sourcing.category_query_map(cats)
    rows = [
        {"query": sourcing._category_term("Surveillance drone batteries"),
         "title": "Grepow", "url": "https://grepow.com/x", "description": "d"},
        {"query": "some generic staple query",  # not a category query → no attribution
         "title": "Other", "url": "https://other.com/y", "description": "d"},
    ]
    cands = sourcing.extract_candidates(rows, cmap)
    by_dom = {c["domain"]: c for c in cands}
    assert by_dom["grepow.com"]["category"] == "Surveillance drone batteries"
    assert by_dom["other.com"]["category"] is None


# --- stage 2: website resolve (pure decision, no network) --------------------
def test_resolve_result_reachable_uses_final_url():
    r = webcheck.resolve_result("https://www.grepow.com/", 200, "https://grepow.com/")
    assert r["website"] == "https://www.grepow.com/" and r["domain"] == "grepow.com"
    assert r["reachable"] is True and r["note"] is None


def test_resolve_result_unreachable_keeps_original_and_flags():
    r = webcheck.resolve_result(None, 0, "https://dead.com/")
    assert r["website"] == "https://dead.com/" and r["reachable"] is False
    assert "unverified" in r["note"]


def test_resolve_result_5xx_is_unverified():
    r = webcheck.resolve_result("https://x.com/", 503, "https://x.com/")
    assert r["reachable"] is False


# --- EXTRACT pass parsing (cheap model) --------------------------------------
def test_parse_profile_extracts_fields_no_band():
    v = claude_classify.parse_profile(
        '{"name":"Grepow","country":"China","category":"Surveillance",'
        '"selling_to":["DJI","Autel"]}',
        ["Surveillance"],
    )
    assert v["name"] == "Grepow" and v["country"] == "China"
    assert v["category"] == "Surveillance" and v["selling_to"] == "DJI, Autel"
    assert "band" not in v  # extract pass never decides the band


def test_parse_profile_junk_falls_back():
    v = claude_classify.parse_profile("not json", ["Survey"])
    assert v["country"] is None and v["selling_to"] is None and v["selling_to_note"]


# --- staged writers: country (3) then selling-to (4), band (5) separate ------
async def test_apply_enrichment_stages_country_then_selling_to(session):
    await service.upsert_discovered(session, [
        {"name": "Grepow", "website": "https://grepow.com/", "domain": "grepow.com",
         "category": "Surveillance"},  # originating-search category
    ])
    item = (await service.list_competitors(session, include_archived=True))[0]
    # stage 3 — country only; category already set by discovery must NOT change
    await service.apply_enrichment(
        session, item.id, country="China", category="Delivery",
        selling_to="ShouldNotWriteYet", write_country=True,
    )
    s3 = await service.get_one(session, item.id)
    assert s3.country == "China" and s3.scope == "global"
    assert s3.category == "Surveillance"      # originating search wins
    assert s3.selling_to is None              # selling-to not written in stage 3
    # stage 4 — selling-to only
    await service.apply_enrichment(
        session, item.id, selling_to="DJI, Autel", write_selling_to=True,
    )
    s4 = await service.get_one(session, item.id)
    assert s4.selling_to == "DJI, Autel"


async def test_apply_enrichment_fills_category_only_when_blank(session):
    await service.upsert_discovered(session, [
        {"name": "X", "website": "https://x.com/", "domain": "x.com"},  # no category
    ])
    item = (await service.list_competitors(session, include_archived=True))[0]
    await service.apply_enrichment(session, item.id, category="Delivery", write_country=True)
    again = await service.get_one(session, item.id)
    assert again.category == "Delivery"  # blank → Claude fallback fills it


async def test_apply_band_writes_only_band(session):
    await service.upsert_discovered(session, [
        {"name": "Y", "website": "https://y.com/", "domain": "y.com", "category": "Survey"},
    ])
    item = (await service.list_competitors(session, include_archived=True))[0]
    await service.apply_enrichment(session, item.id, country="India", write_country=True)
    await service.apply_band(
        session, item.id, band="Sure", reason="maker", confidence="0.9", input_hash="h",
    )
    again = await service.get_one(session, item.id)
    assert again.band == "Sure" and again.band_confidence == "0.9"
    assert again.country == "India" and again.category == "Survey"  # untouched by band


async def test_apply_band_never_silently_sure(session):
    await service.upsert_discovered(session, [
        {"name": "Z", "website": "https://z.com/", "domain": "z.com"},
    ])
    item = (await service.list_competitors(session, include_archived=True))[0]
    await service.apply_band(
        session, item.id, band="Maybe", reason="r", confidence="0", input_hash="h",
    )
    again = await service.get_one(session, item.id)
    assert again.band == "Unsure"  # invalid band clamped, never silently Sure


async def test_set_website_records_flag_and_respects_lock(session):
    await service.upsert_discovered(session, [
        {"name": "W", "website": "https://w.com/", "domain": "w.com"},
    ])
    item = (await service.list_competitors(session, include_archived=True))[0]
    await service.set_website(session, item.id, website="https://www.w.com/",
                              domain="w.com", verified=True)
    a = await service.get_one(session, item.id)
    assert a.website == "https://www.w.com/" and a.website_verified is True
    # lock the website, then a resolve must keep the value but may still flag
    await service.edit_competitor(session, item.id, website="https://locked.com/")
    await service.set_website(session, item.id, website="https://other.com/",
                              domain="other.com", verified=False)
    b = await service.get_one(session, item.id)
    assert b.website == "https://locked.com/" and b.website_verified is False


async def test_competitors_for_sync_returns_all_active_non_manual(session):
    await service.upsert_discovered(session, _rows())
    await service.add_manual(session, name="Man", website="https://man.com/",
                             country=None, category=None, selling_to=None)
    rows = await service.competitors_for_sync(session)
    assert len(rows) == 2 and all(not r.manual for r in rows)
