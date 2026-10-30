"""S-7 lead value (exact INR) + campaign owner + pipeline board sort/filters."""

from __future__ import annotations

from tests.conftest import login, make_user


async def _signin(client, role="rep"):
    await make_user(client, f"{role}@x.com", "pw12345678", role=role)
    await login(client, f"{role}@x.com", "pw12345678")


async def _make_campaign(cid, name, owner):
    import app.db as db_mod
    from app.campaigns.orm import Campaign

    async with db_mod.async_session() as s:
        s.add(
            Campaign(
                id=cid, name=name, owner=owner,
                category_id=1, target_category_id=1, geography_id=1,
                timezone="Asia/Kolkata",
            )
        )
        await s.commit()


async def _make_lead(key, *, campaign_id=None, value_inr=None, stage="new"):
    import app.db as db_mod
    from app.leads.orm import Lead

    async with db_mod.async_session() as s:
        lead = Lead(
            first_name="V", last_name="L", dedup_key=key,
            campaign_id=campaign_id, value_inr=value_inr, stage=stage, source="test",
        )
        s.add(lead)
        await s.commit()
        await s.refresh(lead)
        return lead.id


# ---- value PATCH (audited, exact int) -------------------------------------

async def test_patch_value_sets_and_audits(client):
    await _signin(client)
    lid = await _make_lead("nc:v1")
    r = await client.patch(f"/api/leads/{lid}", json={"value_inr": 250000})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["value_inr"] == 250000
    kinds = [e["kind"] for e in d["events"]]
    assert "value_change" in kinds


async def test_patch_clear_value(client):
    await _signin(client)
    lid = await _make_lead("nc:v2", value_inr=500000)
    r = await client.patch(f"/api/leads/{lid}", json={"clear_value": True})
    assert r.status_code == 200, r.text
    assert r.json()["value_inr"] is None


async def test_negative_value_rejected(client):
    await _signin(client)
    lid = await _make_lead("nc:v3")
    r = await client.patch(f"/api/leads/{lid}", json={"value_inr": -5})
    assert r.status_code == 422


async def test_patch_icebreaker_inline_edit(client):
    await _signin(client)
    lid = await _make_lead("nc:ib1")
    r = await client.patch(f"/api/leads/{lid}", json={"icebreaker": "  hey, saw your fleet  "})
    assert r.status_code == 200, r.text
    assert r.json()["icebreaker"] == "hey, saw your fleet"  # trimmed
    # blank clears it
    r2 = await client.patch(f"/api/leads/{lid}", json={"icebreaker": "   "})
    assert r2.json()["icebreaker"] is None


# ---- board ordering: highest value first, NULLs last ----------------------

async def test_board_orders_value_desc_nulls_last(client):
    await _signin(client)
    await _make_lead("nc:b1", value_inr=100, stage="new")
    await _make_lead("nc:b2", value_inr=900, stage="new")
    await _make_lead("nc:b3", value_inr=None, stage="new")
    await _make_lead("nc:b4", value_inr=500, stage="new")

    board = (await client.get("/api/leads/board")).json()
    new_col = board["columns"]["new"]
    vals = [l["value_inr"] for l in new_col]
    assert vals == [900, 500, 100, None]


# ---- board filters: owner + campaign --------------------------------------

async def test_board_filters_by_owner_and_campaign(client):
    await _signin(client)
    await _make_campaign(1, "Alpha", "Priya")
    await _make_campaign(2, "Beta", "Ravi")
    await _make_lead("nc:f1", campaign_id=1, value_inr=10)
    await _make_lead("nc:f2", campaign_id=2, value_inr=20)

    # owner filter
    b = (await client.get("/api/leads/board?owner=Priya")).json()
    flat = [l for col in b["columns"].values() for l in col]
    assert len(flat) == 1
    assert all(l["campaign_owner"] == "Priya" for l in flat)

    # campaign filter
    b2 = (await client.get("/api/leads/board?campaign_id=2")).json()
    flat2 = [l for col in b2["columns"].values() for l in col]
    assert all(l["campaign_id"] == 2 for l in flat2)

    # option lists are surfaced for the UI
    assert set(b["owner_options"]) >= {"Priya", "Ravi"}
    assert any(c["name"] == "Alpha" for c in b["campaign_options"])


async def test_master_list_exposes_owner_and_value(client):
    await _signin(client)
    await _make_campaign(1, "Alpha", "Priya")
    await _make_lead("nc:m1", campaign_id=1, value_inr=75000)
    rows = (await client.get("/api/leads")).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["campaign_owner"] == "Priya"
    assert row["value_inr"] == 75000
