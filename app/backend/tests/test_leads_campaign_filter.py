"""Central leads list gains a Campaign column + ?campaign_id= filter (S-5)."""

from __future__ import annotations

from tests.conftest import login, make_user


async def _admin(client):
    await make_user(client, "admin@x.com", "pw12345678", role="admin")
    await login(client, "admin@x.com", "pw12345678")


async def _catalog(client, kind, name):
    r = await client.post("/api/config/items", json={"kind": kind, "name": name})
    return r.json()["id"]


async def _campaign(client, name):
    cat = await _catalog(client, "category", f"cat-{name}")
    tgt = await _catalog(client, "target_category", f"tgt-{name}")
    geo = await _catalog(client, "geography", "India")
    await _catalog(client, "role", "Procurement / Sourcing")
    icp = await _catalog(client, "icp_filter", f"icp-{name}")  # S-5c signal
    payload = {
        "name": name, "category_id": cat, "target_category_id": tgt,
        "geography_id": geo, "icp_filter_ids": [icp],
        "timezone": "Asia/Kolkata", "target_lead_count": 5,
        "send_days": ["mon"], "send_start_hour": 9, "send_end_hour": 17,
        "status": "draft", "steps": [{"wait_days": 0, "subject": "s", "body": "b"}],
    }
    return (await client.post("/api/campaigns", json=payload)).json()["id"]


async def _gen(cid, records):
    import app.db as db_mod
    from app.scraping.models import GenerateRequest
    from app.scraping.service import generate_leads

    async def fake(actor_input):
        return records

    async with db_mod.async_session() as session:
        await generate_leads(session, cid, GenerateRequest(cap=5), runner=fake)


def _p(first, last):
    return {
        "first_name": first, "last_name": last,
        "email": f"{first}@x.com".lower(),
        "organization_name": "Acme",
    }


async def test_filter_returns_only_that_campaign(client):
    await _admin(client)
    a = await _campaign(client, "Alpha")
    b = await _campaign(client, "Beta")
    await _gen(a, [_p("Ann", "A"), _p("Al", "A2")])
    await _gen(b, [_p("Ben", "B")])

    a_rows = (await client.get(f"/api/leads?campaign_id={a}")).json()
    b_rows = (await client.get(f"/api/leads?campaign_id={b}")).json()
    assert len(a_rows) == 2 and len(b_rows) == 1
    assert all(r["campaign_name"] == "Alpha" for r in a_rows)
    assert b_rows[0]["campaign_name"] == "Beta"


async def test_central_list_shows_campaign_column(client):
    await _admin(client)
    a = await _campaign(client, "Alpha")
    await _gen(a, [_p("Ann", "A")])
    rows = (await client.get("/api/leads")).json()
    ann = next(r for r in rows if r["first_name"] == "Ann")
    assert ann["campaign_id"] == a
    assert ann["campaign_name"] == "Alpha"


async def test_lead_without_campaign_has_null_campaign(client):
    """A manually-inserted lead with no campaign shows blank campaign fields."""
    await _admin(client)
    import app.db as db_mod
    from app.leads.orm import Lead

    async with db_mod.async_session() as session:
        session.add(
            Lead(
                first_name="No", last_name="Camp", dedup_key="em:nocamp-test",
                stage="new", source="seed",
            )
        )
        await session.commit()
    rows = (await client.get("/api/leads")).json()
    nc = next(r for r in rows if r["first_name"] == "No")
    assert nc["campaign_id"] is None
    assert nc["campaign_name"] is None
