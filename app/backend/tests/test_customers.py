"""mPower's Brain — Customers module tests (deterministic, no network/spend).

Covers the load-bearing invariants mirrored from Competitors PLUS the customer-
specific surface: the OEM/channel two-lane discovery attribution, the Type
(OEM/Reseller/Distributor) snap (a battery manufacturer is NEVER a customer type),
the genuine-customer classifier parse, the staged writers (location → type → band),
and the RESUME-continues fix (resume row-set = band-null only; the /sync endpoint
reuses a paused job instead of re-running discovery).
"""

from __future__ import annotations

import pytest_asyncio

from conftest import login, make_user

from app.customers import claude_classify, discovery, service, sourcing, webcheck


@pytest_asyncio.fixture
async def session(client):
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


# --- normalization, keys, scope ---------------------------------------------
def test_normalize_domain():
    assert service.normalize_domain("https://www.Ideaforge.in/x") == "ideaforge.in"
    assert service.normalize_domain(None) == ""


def test_dedup_key_by_domain_deterministic():
    assert service.dedup_key_synced("https://www.garuda.com/x") == service.dedup_key_synced("garuda.com")


def test_manual_key_never_collides_with_synced():
    assert service.dedup_key_manual("Garuda") != service.dedup_key_synced("garuda.com")


def test_derive_scope_india_is_local():
    assert service.derive_scope("India") == "local"
    assert service.derive_scope("United States") == "global"


# --- idempotent upsert (stores ctype) + manual protection -------------------
def _rows():
    return [
        {"name": "Garuda", "website": "https://garuda.com/", "domain": "garuda.com",
         "country": "India", "category": "Agriculture Spraying", "ctype": "OEM", "source_url": "u1"},
        {"name": "DroneDist", "website": "https://dronedist.com/", "domain": "dronedist.com",
         "country": None, "ctype": None, "source_url": "u2"},
    ]


async def test_upsert_idempotent_and_stores_ctype(session):
    i1, u1, s1 = await service.upsert_discovered(session, _rows())
    assert (i1, u1, s1) == (2, 0, 0)
    rows = await service.list_customers(session, include_archived=True)
    garuda = next(r for r in rows if r.domain == "garuda.com")
    assert garuda.ctype == "OEM" and garuda.scope == "local"
    i2, u2, _ = await service.upsert_discovered(session, _rows())
    assert (i2, u2) == (0, 2)


async def test_sync_never_overwrites_manual_row(session):
    await service.add_manual(session, name="Garuda", website="https://garuda.com/",
                             country="India", category=None, ctype="OEM")
    i, u, skipped = await service.upsert_discovered(session, [
        {"name": "Garuda Inc", "website": "https://garuda.com/", "domain": "garuda.com"},
    ])
    assert skipped == 1 and i == 0


async def test_manual_add_locks_provided_fields_incl_ctype(session):
    m = await service.add_manual(session, name="X", website="https://x.com/",
                                 country="India", category="Survey", ctype="Distributor")
    out = service.to_out(m)
    assert m.scope == "local" and m.band == "Sure"
    assert set(out.locked_fields) == {"name", "website", "country", "category", "ctype"}


async def test_manual_add_clamps_bad_ctype(session):
    m = await service.add_manual(session, name="Y", website=None, country=None,
                                 category=None, ctype="banana")
    assert m.ctype is None  # invalid type clamped, never stored as a guess


# --- robust classifier parsing (band + ctype) -------------------------------
def test_parse_valid_verdict_with_ctype():
    v = claude_classify.parse_classification(
        '{"band":"Sure","reason":"drone maker","confidence":0.9,"country":"India",'
        '"category":"Survey","ctype":"OEM"}',
        ["Survey", "Agriculture Spraying"],
    )
    assert v["band"] == "Sure" and v["confidence"] == "0.9"
    assert v["country"] == "India" and v["category"] == "Survey" and v["ctype"] == "OEM"


def test_parse_junk_falls_back_to_unsure():
    v = claude_classify.parse_classification("not json", ["Survey"])
    assert v["band"] == "Unsure" and v["ctype"] is None


def test_parse_invalid_band_falls_back_to_unsure():
    v = claude_classify.parse_classification('{"band":"Maybe","confidence":1}', ["Survey"])
    assert v["band"] == "Unsure"  # never silently Sure


def test_ctype_snap_variants():
    assert claude_classify._snap_ctype("OEM") == "OEM"
    assert claude_classify._snap_ctype("drone manufacturer") == "OEM"
    assert claude_classify._snap_ctype("Distributor") == "Distributor"
    assert claude_classify._snap_ctype("authorized dealer / reseller") == "Reseller"
    # a battery MAKER is never a customer type
    assert claude_classify._snap_ctype("battery manufacturer") is None
    assert claude_classify._snap_ctype("") is None
    assert claude_classify._snap_ctype("unclear") is None


def test_category_snaps_to_canonical():
    cats = ["Agriculture Spraying drone batteries", "Surveillance drone batteries"]
    v = claude_classify.parse_classification(
        '{"band":"Sure","confidence":1,"category":"Surveillance"}', cats
    )
    assert v["category"] == "Surveillance drone batteries"


def test_category_unrecognized_is_blank_not_guessed():
    v = claude_classify.parse_classification(
        '{"band":"Sure","confidence":1,"category":"Quantum Reactors"}', ["Survey"]
    )
    assert v["category"] is None


def test_parse_profile_extracts_ctype_no_band():
    v = claude_classify.parse_profile(
        '{"name":"Garuda","country":"India","category":"Survey","ctype":"OEM"}', ["Survey"]
    )
    assert v["name"] == "Garuda" and v["country"] == "India" and v["ctype"] == "OEM"
    assert "band" not in v


def test_classifier_system_excludes_battery_makers():
    # the rubric must explicitly band a battery MANUFACTURER as a competitor (No).
    sysprompt = claude_classify.SYSTEM.lower()
    assert "competitor" in sysprompt and "manufactures drone battery" in sysprompt
    assert "oem" in sysprompt and "distributor" in sysprompt


def test_propose_queries_parse():
    qs = claude_classify.parse_queries('{"queries":["drone maker india"," "]}')
    assert qs == ["drone maker india"]


# --- two-lane discovery attribution -----------------------------------------
def test_segment_phrase_anchors_to_drone_and_drops_non_segments():
    from app import segments

    # bare label → drone-anchored (the Google-Maps bug fix)
    assert segments.segment_phrase("Mapping") == "Mapping drone"
    # battery noise stripped so the OEM lane targets drone makers, not battery makers
    assert segments.segment_phrase("Surveillance drone batteries") == "Surveillance drone"
    # already-anchored stays as-is
    assert segments.segment_phrase("Agriculture Spraying").lower().endswith("drone")
    # operational / non-product labels → None (no per-category query)
    assert segments.segment_phrase("Recycling") is None
    assert segments.segment_phrase("B2B sales") is None
    assert segments.segment_phrase("Inverter Batteries") is None


def test_bare_category_queries_are_drone_anchored():
    # "Mapping" must NOT yield "Mapping distributor reseller" (Google-Maps drift)
    oq = sourcing.oem_term("Mapping")
    cq = sourcing.channel_term("Mapping")
    assert "drone" in oq.lower() and "drone" in cq.lower()
    # non-segment category issues no query in either lane
    assert sourcing.oem_term("Recycling") is None
    assert sourcing.channel_term("B2B sales") is None


def test_category_query_map_two_lanes():
    cats = ["Surveillance drone batteries"]
    m = sourcing.category_query_map(cats)
    oem_q = sourcing.oem_term("Surveillance drone batteries")
    chan_q = sourcing.channel_term("Surveillance drone batteries")
    assert m[oem_q] == {"category": "Surveillance drone batteries", "ctype": "OEM"}
    assert m[chan_q] == {"category": "Surveillance drone batteries", "ctype": None}


def test_extract_candidates_attributes_category_and_ctype():
    cats = ["Surveillance drone batteries"]
    cmap = sourcing.category_query_map(cats)
    oem_q = sourcing.oem_term("Surveillance drone batteries")
    rows = [
        {"query": oem_q, "title": "Garuda", "url": "https://garuda.com/x", "description": "d"},
        {"query": "generic staple", "title": "Other", "url": "https://other.com/y", "description": "d"},
    ]
    cands = sourcing.extract_candidates(rows, cmap)
    by_dom = {c["domain"]: c for c in cands}
    assert by_dom["garuda.com"]["category"] == "Surveillance drone batteries"
    assert by_dom["garuda.com"]["ctype"] == "OEM"
    assert by_dom["other.com"]["category"] is None and by_dom["other.com"]["ctype"] is None


def test_seed_queries_round0_has_oem_channel_and_india():
    qs = sourcing.seed_queries(["Surveillance drone batteries"], 0)
    blob = " ".join(qs).lower()
    assert "manufacturer" in blob          # OEM lane
    assert "distributor" in blob or "reseller" in blob  # channel lane
    assert "india" in blob                 # local coverage from round 0


def test_extract_candidates_blocklist_and_dedupe():
    rows = [{"title": d.split(".")[0], "url": f"https://{d}/x", "description": "d"}
            for d in ["garuda.com", "garuda.com", "alibaba.com", "youtube.com", "ideaforge.in"]]
    doms = {c["domain"] for c in sourcing.extract_candidates(rows)}
    assert doms == {"garuda.com", "ideaforge.in"}


async def test_discovery_dedup_and_plateau_stop():
    async def search_fn(queries):
        return [{"title": d, "url": f"https://{d}/x", "description": "d"} for d in ["a.com", "b.com", "c.com"]]

    out = await discovery.run_discovery(
        search_fn=search_fn, propose_fn=None, categories=["Survey"],
        max_rounds=5, plateau_threshold=2, max_queries_per_round=8,
    )
    assert len(out["candidates"]) == 3 and out["rounds"] == 2


# --- staged writers: location (3) → type (4) → band (5) ---------------------
async def test_apply_enrichment_stages_country_then_ctype(session):
    await service.upsert_discovered(session, [
        {"name": "Garuda", "website": "https://garuda.com/", "domain": "garuda.com",
         "category": "Agriculture Spraying"},
    ])
    item = (await service.list_customers(session, include_archived=True))[0]
    # stage 3 — country only; originating category must NOT change; ctype not yet written
    await service.apply_enrichment(
        session, item.id, country="India", category="Delivery",
        ctype="Reseller", write_country=True,
    )
    s3 = await service.get_one(session, item.id)
    assert s3.country == "India" and s3.scope == "local"
    assert s3.category == "Agriculture Spraying"  # originating search wins
    assert s3.ctype is None                        # type not written in stage 3
    # stage 4 — type only
    await service.apply_enrichment(session, item.id, ctype="OEM", write_ctype=True)
    s4 = await service.get_one(session, item.id)
    assert s4.ctype == "OEM"


async def test_apply_enrichment_clamps_bad_ctype(session):
    await service.upsert_discovered(session, [
        {"name": "X", "website": "https://x.com/", "domain": "x.com"},
    ])
    item = (await service.list_customers(session, include_archived=True))[0]
    await service.apply_enrichment(session, item.id, ctype="nonsense", write_ctype=True)
    assert (await service.get_one(session, item.id)).ctype is None


async def test_apply_band_writes_band_and_fills_blank_ctype(session):
    await service.upsert_discovered(session, [
        {"name": "Y", "website": "https://y.com/", "domain": "y.com", "category": "Survey"},
    ])
    item = (await service.list_customers(session, include_archived=True))[0]
    await service.apply_band(
        session, item.id, band="Sure", reason="drone oem", confidence="0.9",
        input_hash="h", ctype="OEM",
    )
    again = await service.get_one(session, item.id)
    assert again.band == "Sure" and again.ctype == "OEM" and again.category == "Survey"


async def test_apply_band_never_silently_sure(session):
    await service.upsert_discovered(session, [
        {"name": "Z", "website": "https://z.com/", "domain": "z.com"},
    ])
    item = (await service.list_customers(session, include_archived=True))[0]
    await service.apply_band(session, item.id, band="Maybe", reason="r",
                             confidence="0", input_hash="h")
    assert (await service.get_one(session, item.id)).band == "Unsure"


async def test_edit_locks_ctype_and_survives_sync(session):
    await service.upsert_discovered(session, [
        {"name": "W", "website": "https://w.com/", "domain": "w.com", "ctype": "OEM"},
    ])
    item = (await service.list_customers(session, include_archived=True))[0]
    await service.edit_customer(session, item.id, ctype="Distributor")
    # a later enrichment proposing OEM must NOT overwrite the locked human value
    await service.apply_enrichment(session, item.id, ctype="OEM", write_ctype=True)
    assert (await service.get_one(session, item.id)).ctype == "Distributor"


# --- RESUME row-set: band-null only -----------------------------------------
async def test_customers_to_classify_is_resume_set(session):
    await service.upsert_discovered(session, [
        {"name": "Done", "website": "https://done.com/", "domain": "done.com"},
        {"name": "Pending", "website": "https://pending.com/", "domain": "pending.com"},
    ])
    rows = await service.list_customers(session, include_archived=True)
    done = next(r for r in rows if r.domain == "done.com")
    # classify "done" with the REAL content hash → it is finished, excluded from resume
    h = service.content_hash(done.name, done.domain)
    await service.apply_band(session, done.id, band="Sure", reason="r",
                             confidence="1", input_hash=h)
    pending = await service.customers_to_classify(session)
    doms = {r.domain for r in pending}
    assert doms == {"pending.com"}  # only the unfinished row resumes


async def test_customers_for_sync_returns_all_active_non_manual(session):
    await service.upsert_discovered(session, _rows())
    await service.add_manual(session, name="Man", website="https://man.com/",
                             country=None, category=None, ctype=None)
    rows = await service.customers_for_sync(session)
    assert len(rows) == 2 and all(not r.manual for r in rows)


# --- stage 2: website resolve (pure decision) -------------------------------
def test_resolve_result_reachable_uses_final_url():
    r = webcheck.resolve_result("https://www.garuda.com/", 200, "https://garuda.com/")
    assert r["website"] == "https://www.garuda.com/" and r["reachable"] is True


def test_resolve_result_unreachable_keeps_original():
    r = webcheck.resolve_result(None, 0, "https://dead.com/")
    assert r["website"] == "https://dead.com/" and r["reachable"] is False


# --- API: admin gate + dev-info + resume endpoint ---------------------------
async def test_list_requires_admin(client):
    await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "rep@buloop.com", "password123")
    assert (await client.get("/api/brain/customers")).status_code == 403


async def test_list_unauthed_401(client):
    assert (await client.get("/api/brain/customers")).status_code == 401


async def test_admin_can_add_and_list(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    res = await client.post(
        "/api/brain/customers",
        json={"name": "Garuda", "website": "https://garuda.com/", "country": "India",
              "category": "Survey", "ctype": "OEM"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["manual"] is True and body["band"] == "Sure"
    assert body["ctype"] == "OEM" and body["scope"] == "local"


async def test_sync_route_rep_forbidden(client):
    await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "rep@buloop.com", "password123")
    assert (await client.post("/api/brain/customers/sync", json={})).status_code == 403


async def test_dev_info_exposes_real_prompt(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    info = (await client.get("/api/brain/customers/dev-info")).json()
    assert "SalesPath Sure" in info["claude_system"]
    assert info["search_actor"] == "apify~google-search-scraper"
    assert info["pipeline_steps"] and "Identify type" in " ".join(info["pipeline_steps"])
    assert info["type_sources"]


async def test_resume_reuses_paused_job_not_a_new_discovery(client):
    """The fix: POST /sync with a PAUSED job RESUMES it (same job id) instead of
    creating a fresh job that re-runs stage-1 discovery."""
    import app.db as db_mod
    from app.jobs import service as jobs_service

    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    async with db_mod.async_session() as s:
        job = await jobs_service.create_job(s, kind="customers_sync", campaign_id=None)
        await jobs_service.mark_paused(s, job.id, message="Paused (12/463).")
        paused_id = job.id

    res = await client.post("/api/brain/customers/sync", json={})
    assert res.status_code == 200
    # SAME job id returned → resumed, not a new discovery job.
    assert res.json()["id"] == paused_id
    # no second customers_sync job was created
    async with db_mod.async_session() as s:
        from sqlalchemy import func, select
        from app.jobs.orm import Job
        n = await s.scalar(
            select(func.count()).select_from(Job).where(Job.kind == "customers_sync")
        )
    assert n == 1


async def test_is_live_false_for_unlaunched_job():
    from app.jobs import runner
    assert runner.is_live(987654) is False  # no task ever launched for this id


async def test_pause_on_orphaned_running_job_marks_paused(client):
    """A 'running' job with no live worker (its task died on a process restart) cannot
    be cooperatively paused — the pause endpoint marks it paused at once so the UI
    doesn't hang on 'Pausing…'."""
    import app.db as db_mod
    from app.jobs import service as jobs_service

    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    async with db_mod.async_session() as s:
        job = await jobs_service.create_job(s, kind="customers_sync", campaign_id=None)
        await jobs_service.mark_running(s, job.id, total=399)  # running, but never launched → orphaned
        orphan_id = job.id

    body = (await client.post("/api/brain/customers/sync/pause", json={})).json()
    assert body["job"]["id"] == orphan_id and body["job"]["status"] == "paused"


async def test_sync_resumes_orphaned_running_job(client):
    """Clicking Sync on an orphaned 'running' job RESUMES it (same id, no re-discovery)
    instead of dedupe-returning a dead job that never progresses."""
    import app.db as db_mod
    from sqlalchemy import func, select
    from app.jobs import service as jobs_service
    from app.jobs.orm import Job

    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    async with db_mod.async_session() as s:
        job = await jobs_service.create_job(s, kind="customers_sync", campaign_id=None)
        await jobs_service.mark_running(s, job.id, total=399)
        orphan_id = job.id

    res = await client.post("/api/brain/customers/sync", json={})
    assert res.status_code == 200 and res.json()["id"] == orphan_id  # resumed, not new
    async with db_mod.async_session() as s:
        n = await s.scalar(
            select(func.count()).select_from(Job).where(Job.kind == "customers_sync")
        )
    assert n == 1  # no fresh discovery job created
