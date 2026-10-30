"""target_lead_count field + generate-status + generate-leads endpoint (S-5).

The generate endpoint is admin-only; Apify is monkeypatched for the happy path
and left unset for the missing-key path (no live call, no credits)."""

from __future__ import annotations

from tests.conftest import login, make_user


async def _admin(client):
    await make_user(client, "admin@x.com", "pw12345678", role="admin")
    await login(client, "admin@x.com", "pw12345678")


async def _catalog(client, kind, name):
    r = await client.post("/api/config/items", json={"kind": kind, "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _campaign(client, *, target=0):
    cat = await _catalog(client, "category", "mPower batteries")
    tgt = await _catalog(client, "target_category", "Agri drones")
    geo = await _catalog(client, "geography", "India")
    await _catalog(client, "role", "Procurement / Sourcing")
    icp = await _catalog(client, "icp_filter", "Drone OEMs")  # S-5c signal
    payload = {
        "name": "C1",
        "category_id": cat,
        "target_category_id": tgt,
        "geography_id": geo,
        "icp_filter_ids": [icp],
        "timezone": "Asia/Kolkata",
        "target_lead_count": target,
        "send_days": ["mon"],
        "send_start_hour": 9,
        "send_end_hour": 17,
        "status": "draft",
        "steps": [{"wait_days": 0, "subject": "Hi", "body": "x"}],
    }
    r = await client.post("/api/campaigns", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_target_defaults_to_zero(client):
    await _admin(client)
    cid = await _campaign(client)  # target omitted -> 0
    d = (await client.get(f"/api/campaigns/{cid}")).json()
    assert d["target_lead_count"] == 0


async def test_target_saved_and_patched(client):
    await _admin(client)
    cid = await _campaign(client, target=20)
    assert (await client.get(f"/api/campaigns/{cid}")).json()["target_lead_count"] == 20
    r = await client.patch(f"/api/campaigns/{cid}", json={"target_lead_count": 50})
    assert r.status_code == 200
    assert r.json()["target_lead_count"] == 50


async def test_negative_target_rejected(client):
    await _admin(client)
    cat = await _catalog(client, "category", "x")
    tgt = await _catalog(client, "target_category", "y")
    geo = await _catalog(client, "geography", "India")
    payload = {
        "name": "C", "category_id": cat, "target_category_id": tgt,
        "geography_id": geo, "timezone": "Asia/Kolkata", "target_lead_count": -1,
        "send_days": ["mon"], "send_start_hour": 9, "send_end_hour": 17,
        "status": "draft", "steps": [{"wait_days": 0, "subject": "s", "body": "b"}],
    }
    assert (await client.post("/api/campaigns", json=payload)).status_code == 422


async def test_campaign_generate_routes_removed(client):
    # 08062026_cr CR-2: the campaign page no longer generates leads (it pulls from
    # the master list). The generate routes were removed → 404/405. The scrape
    # service itself stays unit-tested in test_scrape_service.py.
    await _admin(client)
    cid = await _campaign(client, target=5)
    assert (
        await client.get(f"/api/campaigns/{cid}/generate-status")
    ).status_code == 404
    assert (
        await client.post(f"/api/campaigns/{cid}/generate-leads", json={"cap": 5})
    ).status_code in (404, 405)
