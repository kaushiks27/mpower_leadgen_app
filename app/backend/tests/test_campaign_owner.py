"""S-7 campaign owner (free text) — create/edit/clear via the admin API."""

from __future__ import annotations

from tests.conftest import login, make_user


async def _admin(client):
    await make_user(client, "admin@x.com", "pw12345678", role="admin")
    await login(client, "admin@x.com", "pw12345678")


async def _refs(client):
    async def cat(kind, name):
        r = await client.post("/api/config/items", json={"kind": kind, "name": name})
        return r.json()["id"]

    return (
        await cat("category", "Drones"),
        await cat("target_category", "Agri"),
        await cat("geography", "India"),
    )


def _payload(cat, tgt, geo, **over):
    base = {
        "name": "Owned campaign",
        "category_id": cat,
        "target_category_id": tgt,
        "geography_id": geo,
        "timezone": "Asia/Kolkata",
        "send_days": ["mon"],
        "send_start_hour": 9,
        "send_end_hour": 17,
        "status": "draft",
        "steps": [{"wait_days": 0, "subject": "Hi", "body": "Body"}],
    }
    base.update(over)
    return base


async def test_create_with_owner(client):
    await _admin(client)
    cat, tgt, geo = await _refs(client)
    r = await client.post("/api/campaigns", json=_payload(cat, tgt, geo, owner="  Priya Sharma "))
    assert r.status_code == 201, r.text
    assert r.json()["owner"] == "Priya Sharma"  # trimmed


async def test_create_without_owner_is_null(client):
    await _admin(client)
    cat, tgt, geo = await _refs(client)
    r = await client.post("/api/campaigns", json=_payload(cat, tgt, geo))
    assert r.json()["owner"] is None


async def test_edit_and_clear_owner(client):
    await _admin(client)
    cat, tgt, geo = await _refs(client)
    cid = (await client.post("/api/campaigns", json=_payload(cat, tgt, geo, owner="Ravi"))).json()["id"]

    r = await client.patch(f"/api/campaigns/{cid}", json={"owner": "Asha"})
    assert r.json()["owner"] == "Asha"

    r2 = await client.patch(f"/api/campaigns/{cid}", json={"owner": "  "})
    assert r2.json()["owner"] is None  # whitespace clears
