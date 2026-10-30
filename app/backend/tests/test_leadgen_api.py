"""Generate-Leads API tests — admin gate + list/roles shapes + generate guards."""

from __future__ import annotations

from conftest import login, make_user


async def _admin(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")


async def _seed_customer(name="DroneCo"):
    import app.db as db_mod
    from app.customers.orm import CustomerItem

    async with db_mod.async_session() as s:
        c = CustomerItem(
            name=name, country="India", category="Survey", ctype="OEM",
            scope="local", band="Sure", dedup_key=f"cust-api-{name}",
        )
        s.add(c)
        await s.commit()
        await s.refresh(c)
        return c.id


async def test_lists_requires_admin(client):
    await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "rep@buloop.com", "password123")
    assert (await client.get("/api/leadgen/lists")).status_code == 403


async def test_lists_unauthenticated_401(client):
    assert (await client.get("/api/leadgen/lists")).status_code == 401


async def test_lists_shape(client):
    await _admin(client)
    await _seed_customer()
    body = (await client.get("/api/leadgen/lists")).json()
    assert set(body) == {
        "categories",
        "categories_grouped",
        "types",
        "countries",
        "customers",
        "roles",
    }
    assert set(body["categories_grouped"]) == {"product", "service"}
    # Grouped union must equal the flat category list (same source, no drift).
    grouped = body["categories_grouped"]
    assert sorted(grouped["product"] + grouped["service"]) == sorted(body["categories"])
    assert body["types"] == ["OEM", "Reseller", "Distributor"]
    assert any(c["name"] == "DroneCo" for c in body["customers"])
    assert body["customers"][0]["type"] == "OEM"
    assert body["roles"][0]["group"] == "Procurement & Sourcing"
    assert isinstance(body["roles"][0]["titles"], list)


async def test_roles_endpoint_shape(client):
    await _admin(client)
    roles = (await client.get("/api/leadgen/roles")).json()
    assert {r["group"] for r in roles} >= {"Quality", "Executive & Founder"}


async def test_filtered_customers_query(client):
    await _admin(client)
    await _seed_customer("OemCo")
    rows = (await client.get("/api/leadgen/customers?type=OEM&country=India")).json()
    assert all(r["type"] == "OEM" and r["country"] == "India" for r in rows)
    none = (await client.get("/api/leadgen/customers?type=Distributor")).json()
    assert none == []


async def test_generate_guards(client):
    await _admin(client)
    cid = await _seed_customer("GuardCo")
    # no customer → 400
    r = await client.post("/api/leadgen/generate", json={"customer_ids": [], "role_groups": ["Quality"]})
    assert r.status_code == 400
    # no role group → 400
    r = await client.post("/api/leadgen/generate", json={"customer_ids": [cid], "role_groups": []})
    assert r.status_code == 400
    # no apify key → 400
    r = await client.post(
        "/api/leadgen/generate", json={"customer_ids": [cid], "role_groups": ["Quality"]}
    )
    assert r.status_code == 400
    assert "Apify" in r.json()["detail"]


async def test_widen_guards(client):
    await _admin(client)
    # unknown job → 404
    r = await client.post("/api/leadgen/widen", json={"job_id": 999999, "approve": False})
    assert r.status_code == 404
    # an existing job that is NOT awaiting a widen decision → 400
    import app.db as db_mod
    from app.jobs import service as jobs_service
    async with db_mod.async_session() as s:
        job = await jobs_service.create_job(s, kind="generate_leads", campaign_id=None)
        jid = job.id
    r = await client.post("/api/leadgen/widen", json={"job_id": jid, "approve": False})
    assert r.status_code == 400


async def test_dev_info_shape(client):
    await _admin(client)
    info = (await client.get("/api/leadgen/dev-info")).json()
    assert "linkedin_actor" in info
    assert isinstance(info["fallback_actors"], list)
    assert "sample_actor_input" in info
    assert "widen_system" in info and info["widen_system"]
