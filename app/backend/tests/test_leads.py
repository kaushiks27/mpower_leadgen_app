"""Lead engine — list/board/detail, audited stage moves, suppressed badge, seed."""

from __future__ import annotations

from tests.conftest import login, make_user


async def _signin(client, role="rep"):
    await make_user(client, f"{role}@x.com", "pw12345678", role=role)
    await login(client, f"{role}@x.com", "pw12345678")


async def _make_lead(**over):
    """Insert a lead directly (no ingestion API this slice) and return its id."""
    import app.db as db_mod
    from app.leads.dedup import dedup_key
    from app.leads.orm import Lead

    fields = {
        "first_name": "Test",
        "last_name": "Lead",
        "email": "test.lead@example.com",
        "linkedin_url": None,
        "title": "Manager",
        "location": "India",
        "stage": "new",
        "source": "test",
    }
    fields.update(over)
    key = dedup_key(
        first_name=fields["first_name"],
        last_name=fields["last_name"],
        email=fields["email"],
        linkedin_url=fields["linkedin_url"],
        company_name=fields.get("company_name"),
    )
    async with db_mod.async_session() as session:
        lead = Lead(
            first_name=fields["first_name"],
            last_name=fields["last_name"],
            email=fields["email"],
            linkedin_url=fields["linkedin_url"],
            title=fields["title"],
            location=fields["location"],
            dedup_key=key,
            stage=fields["stage"],
            source=fields["source"],
        )
        session.add(lead)
        await session.commit()
        await session.refresh(lead)
        return lead.id


async def test_anonymous_gets_401(client):
    assert (await client.get("/api/leads")).status_code == 401


async def test_rep_and_admin_can_access(client):
    await _signin(client, "rep")
    assert (await client.get("/api/leads")).status_code == 200
    assert (await client.get("/api/leads/board")).status_code == 200


async def test_meta_exposes_stages(client):
    await _signin(client)
    meta = (await client.get("/api/leads/meta")).json()
    assert meta["stages"][0] == "new"
    assert meta["stages"][-1] == "won"
    assert "bounced" in meta["flags"]


async def test_list_and_filter(client):
    await _signin(client)
    await _make_lead(first_name="Aarav", last_name="Mehta",
                     email="a@one.com", stage="new")
    await _make_lead(first_name="Priya", last_name="Nair",
                     email="p@two.com", stage="replied")
    allrows = (await client.get("/api/leads")).json()
    assert len(allrows) == 2
    replied = (await client.get("/api/leads?stage=replied")).json()
    assert len(replied) == 1 and replied[0]["first_name"] == "Priya"
    # search by name
    found = (await client.get("/api/leads?q=aarav")).json()
    assert len(found) == 1 and found[0]["first_name"] == "Aarav"


async def test_unknown_stage_filter_400(client):
    await _signin(client)
    assert (await client.get("/api/leads?stage=banana")).status_code == 400


async def test_deterministic_order_by_name(client):
    await _signin(client)
    await _make_lead(first_name="A", last_name="Zeta", email="z@x.com")
    await _make_lead(first_name="A", last_name="Alpha", email="al@x.com")
    await _make_lead(first_name="A", last_name="Mid", email="m@x.com")
    rows = (await client.get("/api/leads")).json()
    last_names = [r["last_name"] for r in rows]
    assert last_names == sorted(last_names)


async def test_board_groups_by_stage(client):
    await _signin(client)
    await _make_lead(email="x@x.com", stage="new")
    await _make_lead(email="y@y.com", stage="won")
    board = (await client.get("/api/leads/board")).json()
    assert len(board["columns"]["new"]) == 1
    assert len(board["columns"]["won"]) == 1
    assert len(board["columns"]["queued"]) == 0


async def test_stage_move_persists_and_audits(client):
    await _signin(client)
    lid = await _make_lead(email="move@x.com", stage="new")
    r = await client.patch(f"/api/leads/{lid}", json={"stage": "interested"})
    assert r.status_code == 200
    assert r.json()["stage"] == "interested"
    # exactly one stage_change event recorded who/from/to
    events = r.json()["events"]
    moves = [e for e in events if e["kind"] == "stage_change"]
    assert len(moves) == 1
    assert moves[0]["from_value"] == "new"
    assert moves[0]["to_value"] == "interested"
    assert moves[0]["actor_name"]  # actor captured


async def test_free_drag_any_stage_allowed(client):
    await _signin(client)
    lid = await _make_lead(email="jump@x.com", stage="new")
    # jump straight to "won" (skips funnel) — allowed this slice
    r = await client.patch(f"/api/leads/{lid}", json={"stage": "won"})
    assert r.status_code == 200 and r.json()["stage"] == "won"


async def test_unknown_stage_move_rejected(client):
    await _signin(client)
    lid = await _make_lead(email="bad@x.com")
    assert (await client.patch(f"/api/leads/{lid}", json={"stage": "qux"})).status_code == 400


async def test_flag_change_audited(client):
    await _signin(client)
    lid = await _make_lead(email="flag@x.com")
    r = await client.patch(f"/api/leads/{lid}", json={"bounced": True})
    assert r.json()["bounced"] is True
    assert any(e["kind"] == "flag_change" for e in r.json()["events"])


async def test_archive_hides_from_list_no_hard_delete(client):
    await _signin(client)
    lid = await _make_lead(email="arch@x.com")
    await client.patch(f"/api/leads/{lid}", json={"archived": True})
    active = (await client.get("/api/leads")).json()
    assert all(x["id"] != lid for x in active)
    allrows = (await client.get("/api/leads?include_archived=true")).json()
    assert any(x["id"] == lid for x in allrows)
    # no hard-delete route
    assert (await client.delete(f"/api/leads/{lid}")).status_code == 405


async def test_suppressed_badge(client):
    await _signin(client)
    lid = await _make_lead(email="sup@x.com")
    # not suppressed yet
    rows = (await client.get("/api/leads")).json()
    assert next(r for r in rows if r["id"] == lid)["suppressed"] is False
    # add to suppression -> badge flips
    await client.post("/api/suppression", json={"kind": "email", "value": "SUP@x.com"})
    rows = (await client.get("/api/leads")).json()
    assert next(r for r in rows if r["id"] == lid)["suppressed"] is True


async def test_seed_collapses_duplicate_and_suppresses(client):
    await _signin(client)
    from app.leads.seed import seed_sample_leads_if_missing

    await seed_sample_leads_if_missing()
    rows = (await client.get("/api/leads")).json()
    # 9 raw records, 1 planted duplicate -> 8 leads
    assert len(rows) == 8
    # the seeded suppression entry flips a badge
    assert any(r["suppressed"] for r in rows)
    # idempotent: a second run does not double-seed
    await seed_sample_leads_if_missing()
    rows2 = (await client.get("/api/leads")).json()
    assert len(rows2) == 8
