"""Config catalog CRUD — admin-gated, soft-archive only, deterministic order."""

from __future__ import annotations

from tests.conftest import login, make_user


async def _admin(client):
    await make_user(client, "admin@x.com", "pw12345678", role="admin")
    await login(client, "admin@x.com", "pw12345678")


async def test_rep_cannot_access_catalog(client):
    await make_user(client, "rep@x.com", "pw12345678", role="rep")
    await login(client, "rep@x.com", "pw12345678")
    assert (await client.get("/api/config/items")).status_code == 403
    r = await client.post("/api/config/items", json={"kind": "category", "name": "X"})
    assert r.status_code == 403


async def test_anonymous_gets_401(client):
    assert (await client.get("/api/config/items")).status_code == 401


async def test_create_list_archive_flow(client):
    await _admin(client)

    # create
    r = await client.post(
        "/api/config/items",
        json={"kind": "geography", "name": "India", "value": None},
    )
    assert r.status_code == 201
    item = r.json()
    assert item["kind"] == "geography"
    assert item["name"] == "India"
    assert item["archived"] is False
    item_id = item["id"]

    # active list includes it
    rows = (await client.get("/api/config/items")).json()
    assert any(i["id"] == item_id for i in rows)

    # archive (soft) — disappears from active list, stays under include_archived
    r = await client.patch(f"/api/config/items/{item_id}", json={"archived": True})
    assert r.status_code == 200
    assert r.json()["archived"] is True
    active = (await client.get("/api/config/items")).json()
    assert all(i["id"] != item_id for i in active)
    allrows = (await client.get("/api/config/items?include_archived=true")).json()
    assert any(i["id"] == item_id for i in allrows)

    # restore
    r = await client.patch(f"/api/config/items/{item_id}", json={"archived": False})
    assert r.json()["archived"] is False


async def test_edit_name_and_value(client):
    await _admin(client)
    item_id = (
        await client.post("/api/config/items", json={"kind": "role", "name": "Buyer"})
    ).json()["id"]
    r = await client.patch(
        f"/api/config/items/{item_id}",
        json={"name": "Procurement", "value": "decision maker"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Procurement"
    assert r.json()["value"] == "decision maker"


async def test_both_category_kinds_accepted(client):
    await _admin(client)
    for kind in ("category", "target_category"):
        r = await client.post(
            "/api/config/items", json={"kind": kind, "name": f"X-{kind}"}
        )
        assert r.status_code == 201
        assert r.json()["kind"] == kind


async def test_invalid_kind_rejected(client):
    await _admin(client)
    r = await client.post("/api/config/items", json={"kind": "bogus", "name": "X"})
    assert r.status_code == 400
    r = await client.get("/api/config/items?kind=bogus")
    assert r.status_code == 400


async def test_no_hard_delete_route(client):
    await _admin(client)
    item_id = (
        await client.post("/api/config/items", json={"kind": "category", "name": "Y"})
    ).json()["id"]
    # No DELETE endpoint — archiving is the only removal path.
    r = await client.delete(f"/api/config/items/{item_id}")
    assert r.status_code == 405


async def test_deterministic_order_by_kind_name_id(client):
    await _admin(client)
    for name in ("Zeta", "Alpha", "Mu"):
        await client.post("/api/config/items", json={"kind": "category", "name": name})
    rows = (await client.get("/api/config/items?kind=category")).json()
    names = [r["name"] for r in rows]
    assert names == sorted(names)
