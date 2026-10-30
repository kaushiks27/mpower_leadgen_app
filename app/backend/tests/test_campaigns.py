"""Campaign builder CRUD — admin-gated, soft-archive only, validated sequence."""

from __future__ import annotations

from tests.conftest import login, make_user


async def _admin(client):
    await make_user(client, "admin@x.com", "pw12345678", role="admin")
    await login(client, "admin@x.com", "pw12345678")


async def _catalog(client, kind, name):
    """Create a catalog item (admin must be logged in) and return its id."""
    r = await client.post("/api/config/items", json={"kind": kind, "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _seed_refs(client):
    """Create one category, target_category, geography; return their ids."""
    cat = await _catalog(client, "category", "Industrial drones")
    tgt = await _catalog(client, "target_category", "Agri equipment")
    geo = await _catalog(client, "geography", "India")
    return cat, tgt, geo


def _payload(cat, tgt, geo, **over):
    base = {
        "name": "Drone OEMs — India",
        "category_id": cat,
        "target_category_id": tgt,
        "geography_id": geo,
        "timezone": "Asia/Kolkata",
        "send_days": ["mon", "tue", "wed", "thu", "fri"],
        "send_start_hour": 9,
        "send_end_hour": 17,
        "status": "draft",
        "steps": [
            {"wait_days": 0, "subject": "Hi {first_name}", "body": "About {company}"},
            {"wait_days": 3, "subject": "Following up", "body": "Re {company}"},
        ],
    }
    base.update(over)
    return base


async def test_rep_cannot_access_campaigns(client):
    await make_user(client, "rep@x.com", "pw12345678", role="rep")
    await login(client, "rep@x.com", "pw12345678")
    assert (await client.get("/api/campaigns")).status_code == 403
    r = await client.post("/api/campaigns", json={"name": "X"})
    assert r.status_code == 403


async def test_anonymous_gets_401(client):
    assert (await client.get("/api/campaigns")).status_code == 401


async def test_create_list_detail_flow(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    r = await client.post("/api/campaigns", json=_payload(cat, tgt, geo))
    assert r.status_code == 201, r.text
    c = r.json()
    cid = c["id"]
    assert c["category_name"] == "Industrial drones"
    assert c["geography_name"] == "India"
    assert c["step_count"] == 2
    # steps come back ordered + numbered
    assert [s["step_order"] for s in c["steps"]] == [1, 2]
    assert c["steps"][0]["wait_days"] == 0

    # list includes it
    rows = (await client.get("/api/campaigns")).json()
    assert any(x["id"] == cid for x in rows)

    # detail returns ordered steps
    d = (await client.get(f"/api/campaigns/{cid}")).json()
    assert d["steps"][1]["subject"] == "Following up"


async def test_name_required(client):
    # 08062026_cr CR-3/4/5: the create modal collects only name + leads + toggle.
    # Taxonomy refs are now optional; only a non-blank name is required.
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    blank = _payload(cat, tgt, geo, name="   ")
    assert (await client.post("/api/campaigns", json=blank)).status_code == 400


async def test_create_minimal_modal_payload(client):
    # CR-3/4/5: a campaign can be created with just a name (no dropdowns/steps).
    await _admin(client)
    r = await client.post(
        "/api/campaigns",
        json={"name": "Modal-created", "require_icebreaker": True},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Modal-created"
    assert body["require_icebreaker"] is True
    assert body["steps"] == []
    # Timezone defaults to the mPower canonical when no leads are pulled.
    assert body["timezone"] == "Asia/Kolkata"


async def test_steps_optional_at_create(client):
    # CR-3/4/5: steps are added on the detail page, not at create.
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    r = await client.post("/api/campaigns", json=_payload(cat, tgt, geo, steps=[]))
    assert r.status_code == 201


async def test_step_needs_subject_and_body(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    steps = [{"wait_days": 0, "subject": "  ", "body": "x"}]
    r = await client.post("/api/campaigns", json=_payload(cat, tgt, geo, steps=steps))
    assert r.status_code == 400


async def test_invalid_timezone_rejected(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    r = await client.post(
        "/api/campaigns", json=_payload(cat, tgt, geo, timezone="Mars/Phobos")
    )
    assert r.status_code == 400


async def test_invalid_catalog_ref_rejected(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    # geography id that is actually a category -> wrong kind
    r = await client.post(
        "/api/campaigns", json=_payload(cat, tgt, geo, geography_id=cat)
    )
    assert r.status_code == 400
    # non-existent id
    r = await client.post(
        "/api/campaigns", json=_payload(cat, tgt, geo, category_id=99999)
    )
    assert r.status_code == 400


async def test_archived_catalog_ref_rejected(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    await client.patch(f"/api/config/items/{cat}", json={"archived": True})
    r = await client.post("/api/campaigns", json=_payload(cat, tgt, geo))
    assert r.status_code == 400


async def test_invalid_send_hours_rejected(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    r = await client.post(
        "/api/campaigns",
        json=_payload(cat, tgt, geo, send_start_hour=17, send_end_hour=9),
    )
    assert r.status_code == 400


async def test_invalid_send_day_rejected(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    r = await client.post(
        "/api/campaigns", json=_payload(cat, tgt, geo, send_days=["mon", "funday"])
    )
    assert r.status_code == 400


async def test_invalid_status_rejected(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    r = await client.post(
        "/api/campaigns", json=_payload(cat, tgt, geo, status="launched")
    )
    assert r.status_code == 400


async def test_edit_fields_and_status(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    cid = (await client.post("/api/campaigns", json=_payload(cat, tgt, geo))).json()["id"]
    r = await client.patch(
        f"/api/campaigns/{cid}", json={"name": "Renamed", "status": "active"}
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    assert r.json()["status"] == "active"


async def test_patch_replaces_steps(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    cid = (await client.post("/api/campaigns", json=_payload(cat, tgt, geo))).json()["id"]
    new_steps = [{"wait_days": 0, "subject": "Only one", "body": "single step"}]
    r = await client.patch(f"/api/campaigns/{cid}", json={"steps": new_steps})
    assert r.status_code == 200
    assert r.json()["step_count"] == 1
    assert r.json()["steps"][0]["subject"] == "Only one"


async def test_archive_hides_from_active_list(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    cid = (await client.post("/api/campaigns", json=_payload(cat, tgt, geo))).json()["id"]
    await client.patch(f"/api/campaigns/{cid}", json={"archived": True})
    active = (await client.get("/api/campaigns")).json()
    assert all(x["id"] != cid for x in active)
    allrows = (await client.get("/api/campaigns?include_archived=true")).json()
    assert any(x["id"] == cid for x in allrows)


async def test_no_hard_delete_route(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    cid = (await client.post("/api/campaigns", json=_payload(cat, tgt, geo))).json()["id"]
    r = await client.delete(f"/api/campaigns/{cid}")
    assert r.status_code == 405


async def test_deterministic_order_by_name(client):
    await _admin(client)
    cat, tgt, geo = await _seed_refs(client)
    for name in ("Zeta", "Alpha", "Mu"):
        await client.post("/api/campaigns", json=_payload(cat, tgt, geo, name=name))
    rows = (await client.get("/api/campaigns")).json()
    names = [r["name"] for r in rows]
    assert names == sorted(names)
