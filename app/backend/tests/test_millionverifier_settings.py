"""MillionVerifier key appears in Settings + enrich/ceiling endpoints (admin)."""

from __future__ import annotations

from tests.conftest import login, make_user


async def _admin(client):
    await make_user(client, "admin@x.com", "pw12345678", role="admin")
    await login(client, "admin@x.com", "pw12345678")


async def _catalog(client, kind, name):
    r = await client.post("/api/config/items", json={"kind": kind, "name": name})
    return r.json()["id"]


async def _campaign(client):
    cat = await _catalog(client, "category", "Batteries")
    tgt = await _catalog(client, "target_category", "Drones")
    geo = await _catalog(client, "geography", "India")
    icp = await _catalog(client, "icp_filter", "Drone OEMs")
    payload = {
        "name": "C1", "category_id": cat, "target_category_id": tgt,
        "geography_id": geo, "icp_filter_ids": [icp], "timezone": "Asia/Kolkata",
        "target_lead_count": 0, "send_days": ["mon"], "send_start_hour": 9,
        "send_end_hour": 17, "status": "draft",
        "steps": [{"wait_days": 0, "subject": "Hi", "body": "x"}],
    }
    return (await client.post("/api/campaigns", json=payload)).json()["id"]


async def test_millionverifier_listed_as_key_provider(client):
    await _admin(client)
    rows = (await client.get("/api/settings/keys")).json()
    providers = {r["provider"] for r in rows}
    assert "millionverifier" in providers


async def test_millionverifier_key_can_be_saved(client):
    await _admin(client)
    r = await client.put(
        "/api/settings/keys/millionverifier", json={"api_key": "mv-secret-1234"}
    )
    assert r.status_code == 200
    assert r.json()["is_set"] is True and r.json()["last4"] == "1234"


async def test_ceilings_listed_and_settable(client):
    await _admin(client)
    rows = (await client.get("/api/enrichment/ceilings")).json()
    providers = {r["provider"] for r in rows}
    assert providers == {"apollo", "millionverifier"}
    # All default to 0 (no limit).
    assert all(r["monthly_limit"] == 0 and r["remaining"] is None for r in rows)

    r = await client.put("/api/enrichment/ceilings/apollo", json={"monthly_limit": 500})
    assert r.status_code == 200
    body = r.json()
    assert body["monthly_limit"] == 500 and body["remaining"] == 500

    # Unknown provider -> 400.
    assert (
        await client.put("/api/enrichment/ceilings/nope", json={"monthly_limit": 1})
    ).status_code == 400


async def test_ceilings_admin_only(client):
    await _admin(client)
    await make_user(client, "rep@x.com", "pw12345678", role="rep")
    await login(client, "rep@x.com", "pw12345678")
    assert (await client.get("/api/enrichment/ceilings")).status_code == 403


async def test_campaign_enrich_routes_removed(client):
    # 08062026_cr CR-2: the campaign-scoped enrich routes were removed (enrichment
    # now happens in the master Generate-Leads wizard). They must 404/405.
    await _admin(client)
    cid = await _campaign(client)
    assert (
        await client.post(f"/api/campaigns/{cid}/enrich", json={"cap": 25})
    ).status_code in (404, 405)
    assert (
        await client.get(f"/api/campaigns/{cid}/enrich-status")
    ).status_code == 404
