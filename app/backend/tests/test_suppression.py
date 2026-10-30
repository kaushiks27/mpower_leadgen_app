"""Suppression list — normalize, dedupe, soft-remove, role access."""

from __future__ import annotations

from tests.conftest import login, make_user


async def _signin(client, role="rep"):
    await make_user(client, f"{role}@x.com", "pw12345678", role=role)
    await login(client, f"{role}@x.com", "pw12345678")


async def test_anonymous_gets_401(client):
    assert (await client.get("/api/suppression")).status_code == 401


async def test_rep_can_manage(client):
    await _signin(client, "rep")
    r = await client.post(
        "/api/suppression", json={"kind": "email", "value": "  Foo@Bar.com "}
    )
    assert r.status_code == 201, r.text
    assert r.json()["value"] == "foo@bar.com"  # normalized
    rows = (await client.get("/api/suppression")).json()
    assert any(x["value"] == "foo@bar.com" for x in rows)


async def test_linkedin_normalized(client):
    await _signin(client)
    r = await client.post(
        "/api/suppression",
        json={"kind": "linkedin_url", "value": "https://www.LinkedIn.com/in/Jane-Doe/"},
    )
    assert r.status_code == 201
    assert r.json()["value"] == "linkedin.com/in/jane-doe"


async def test_invalid_kind_rejected(client):
    await _signin(client)
    r = await client.post("/api/suppression", json={"kind": "phone", "value": "x"})
    assert r.status_code == 400


async def test_duplicate_reactivates_not_errors(client):
    await _signin(client)
    a = await client.post(
        "/api/suppression", json={"kind": "email", "value": "dup@x.com"}
    )
    aid = a.json()["id"]
    # remove (soft) then re-add the same value -> reactivates same row, no 500
    await client.delete(f"/api/suppression/{aid}")
    b = await client.post(
        "/api/suppression", json={"kind": "email", "value": "DUP@x.com"}
    )
    assert b.status_code == 201
    assert b.json()["id"] == aid
    assert b.json()["active"] is True


async def test_soft_delete_hides_from_active(client):
    await _signin(client)
    r = await client.post(
        "/api/suppression", json={"kind": "email", "value": "gone@x.com"}
    )
    eid = r.json()["id"]
    assert (await client.delete(f"/api/suppression/{eid}")).status_code == 204
    active = (await client.get("/api/suppression")).json()
    assert all(x["id"] != eid for x in active)
    allrows = (await client.get("/api/suppression?include_inactive=true")).json()
    assert any(x["id"] == eid and x["active"] is False for x in allrows)


async def test_delete_missing_404(client):
    await _signin(client)
    assert (await client.delete("/api/suppression/99999")).status_code == 404


async def test_deterministic_order(client):
    await _signin(client)
    for v in ("zed@x.com", "alpha@x.com", "mid@x.com"):
        await client.post("/api/suppression", json={"kind": "email", "value": v})
    rows = (await client.get("/api/suppression")).json()
    vals = [r["value"] for r in rows]
    assert vals == sorted(vals)
