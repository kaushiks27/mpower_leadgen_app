"""Generate-Leads orchestration — dedup against central, cap, target gating,
cross-campaign contact-once. Apify is faked (no live call, no credits)."""

from __future__ import annotations

from tests.conftest import login, make_user


async def _admin(client):
    await make_user(client, "admin@x.com", "pw12345678", role="admin")
    await login(client, "admin@x.com", "pw12345678")


async def _catalog(client, kind, name, value=None):
    body = {"kind": kind, "name": name}
    if value is not None:
        body["value"] = value
    r = await client.post("/api/config/items", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _campaign(client, *, target=0, with_icp=True):
    """Create a campaign and return its id.

    By default selects one ICP filter so the S-5c company-signal guard is
    satisfied (generation allowed). Pass with_icp=False to test the guard.
    """
    cat = await _catalog(client, "category", "mPower batteries")
    tgt = await _catalog(client, "target_category", "Agri drones")
    geo = await _catalog(client, "geography", "India")
    await _catalog(client, "role", "Procurement / Sourcing")
    icp = await _catalog(
        client, "icp_filter", "Drone OEMs / Manufacturers",
        value="drone manufacturer, drone OEM",
    )
    payload = {
        "name": "Drone OEMs — India",
        "category_id": cat,
        "target_category_id": tgt,
        "geography_id": geo,
        "icp_filter_ids": [icp] if with_icp else [],
        "timezone": "Asia/Kolkata",
        "target_lead_count": target,
        "send_days": ["mon"],
        "send_start_hour": 9,
        "send_end_hour": 17,
        "status": "draft",
        "steps": [{"wait_days": 0, "subject": "Hi", "body": "About {company}"}],
    }
    r = await client.post("/api/campaigns", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _person(first, last, **over):
    base = {
        "first_name": first,
        "last_name": last,
        "email": f"{first}.{last}@acme.com".lower(),
        "linkedin_url": f"https://linkedin.com/in/{first}-{last}".lower(),
        "title": "Head of Procurement",
        "organization_name": "Acme Drones",
        "city": "Pune",
    }
    base.update(over)
    return base


async def _generate(cid, cap, records, *, active_90d=True):
    """Call the service directly with a fake runner returning `records`."""
    import app.db as db_mod
    from app.scraping.models import GenerateRequest
    from app.scraping.service import generate_leads

    async def fake_runner(actor_input):
        fake_runner.last_input = actor_input
        return records

    async with db_mod.async_session() as session:
        res = await generate_leads(
            session, cid, GenerateRequest(cap=cap, active_90d=active_90d),
            runner=fake_runner,
        )
    return res, fake_runner


async def test_creates_deduped_leads_tagged_to_campaign(client):
    await _admin(client)
    cid = await _campaign(client, target=5)
    records = [_person("Ann", "Lee"), _person("Bob", "Roy"), _person("Ann", "Lee")]
    res, _ = await _generate(cid, 5, records)
    assert res.created == 2
    assert res.skipped_duplicates == 1  # the repeated Ann Lee
    assert res.campaign_total == 2
    rows = (await client.get(f"/api/leads?campaign_id={cid}")).json()
    assert len(rows) == 2
    assert all(r["source"] == "apify" and r["stage"] == "new" for r in rows)
    assert all(r["campaign_id"] == cid for r in rows)
    assert {r["campaign_name"] for r in rows} == {"Drone OEMs — India"}


async def test_query_built_from_campaign_targeting(client):
    await _admin(client)
    cid = await _campaign(client, target=5)
    _, runner = await _generate(cid, 3, [])
    inp = runner.last_input
    assert inp["fetch_count"] == 3
    assert inp["contact_location"] == ["india"]  # lowercased for Apify enum
    # ICP value drives company_keywords (drone-anchored, comma-split); target
    # category NOT included (S-5d strict-drone).
    assert inp["company_keywords"] == ["drone manufacturer", "drone OEM"]
    assert "procurement" in inp["contact_job_title"]


async def test_no_role_selection_falls_back_to_all_roles(client):
    """S-5b: a campaign with no selected roles searches every active role."""
    await _admin(client)
    cid = await _campaign(client, target=5)  # creates campaign WITHOUT role_ids
    # add a second, distinct role to the catalog so "all roles" is observable
    await _catalog(client, "role", "Founder / CEO")
    _, runner = await _generate(cid, 3, [])
    titles = runner.last_input["contact_job_title"]
    assert "procurement" in titles and "founder" in titles  # both buckets present


async def test_selected_roles_and_icp_drive_query(client):
    """S-5b: only the campaign's chosen roles search; ICP folds into keywords."""
    await _admin(client)
    cat = await _catalog(client, "category", "mPower batteries")
    tgt = await _catalog(client, "target_category", "Agri drones")
    geo = await _catalog(client, "geography", "India")
    r_proc = await _catalog(client, "role", "Procurement / Sourcing")
    await _catalog(client, "role", "Founder / CEO")  # NOT selected
    icp = await _catalog(
        client, "icp_filter", "Drone OEMs / Manufacturers",
        value="drone manufacturer, drone OEM",
    )

    payload = {
        "name": "Selected targeting",
        "category_id": cat,
        "target_category_id": tgt,
        "geography_id": geo,
        "role_ids": [r_proc],
        "icp_filter_ids": [icp],
        "timezone": "Asia/Kolkata",
        "send_days": ["mon"],
        "send_start_hour": 9,
        "send_end_hour": 17,
        "status": "draft",
        "steps": [{"wait_days": 0, "subject": "Hi", "body": "About {company}"}],
    }
    r = await client.post("/api/campaigns", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role_ids"] == [r_proc]
    assert body["icp_filter_ids"] == [icp]
    cid = body["id"]

    _, runner = await _generate(cid, 3, [])
    inp = runner.last_input
    # only the selected Procurement bucket -> founder/ceo absent
    assert inp["contact_job_title"] == ["procurement", "sourcing"]
    # ICP value drives company_keywords (drone-anchored); no target category
    assert inp["company_keywords"] == ["drone manufacturer", "drone OEM"]


async def test_generate_blocked_without_icp_signal(client):
    """S-5c: no ICP selected -> generation refuses (no credits spent)."""
    from app.scraping.service import NO_SIGNAL_MESSAGE, ScrapeError

    await _admin(client)
    cid = await _campaign(client, with_icp=False)  # no buyer signal
    ran = False

    async def fail_if_called(actor_input):
        nonlocal ran
        ran = True
        return []

    import app.db as db_mod
    from app.scraping.models import GenerateRequest
    from app.scraping.service import generate_leads

    async with db_mod.async_session() as session:
        try:
            await generate_leads(
                session, cid, GenerateRequest(cap=5), runner=fail_if_called
            )
            assert False, "expected ScrapeError"
        except ScrapeError as e:
            assert str(e) == NO_SIGNAL_MESSAGE
    assert ran is False  # Apify never called -> no credits spent


# 08062026_cr CR-2: the campaign generate-status route was removed (campaigns
# pull leads from the master list now). Route-removal is asserted in
# test_campaign_target.py::test_campaign_generate_routes_removed. The scrape
# service's signal-gating logic stays covered by the service-level tests above.


async def test_cap_caps_created(client):
    await _admin(client)
    cid = await _campaign(client, target=0)  # no target -> cap governs
    records = [_person(f"P{i}", "X") for i in range(10)]
    res, _ = await _generate(cid, 4, records)
    assert res.created == 4
    assert res.fetched == 10


async def test_effective_cap_limited_by_remaining_to_target(client):
    await _admin(client)
    cid = await _campaign(client, target=3)
    records = [_person(f"P{i}", "X") for i in range(10)]
    res, runner = await _generate(cid, 5, records)
    # remaining to target (3) < cap (5) -> only 3 created, and Apify asked for 3
    assert res.created == 3
    assert runner.last_input["fetch_count"] == 3
    assert res.remaining == 0 and res.can_generate is False


async def test_target_met_short_circuits(client):
    await _admin(client)
    cid = await _campaign(client, target=2)
    await _generate(cid, 5, [_person("A", "A"), _person("B", "B")])
    # already at target -> second run does nothing
    res, runner = await _generate(cid, 5, [_person("C", "C")])
    assert res.created == 0
    assert res.can_generate is False
    assert "met" in res.message.lower()


async def test_skips_records_with_no_identity(client):
    await _admin(client)
    cid = await _campaign(client, target=0)
    records = [{"title": "ghost"}, _person("Real", "Person")]
    res, _ = await _generate(cid, 5, records)
    assert res.created == 1
    assert res.skipped_no_identity == 1


async def test_cross_campaign_contact_once(client):
    await _admin(client)
    cid_a = await _campaign(client, target=5)
    cid_b = await _campaign(client, target=5)
    shared = _person("Shared", "Lead")
    res_a, _ = await _generate(cid_a, 5, [shared])
    assert res_a.created == 1
    # campaign B finds the same person -> skipped, stays with A, B's count stays 0
    res_b, _ = await _generate(cid_b, 5, [shared])
    assert res_b.created == 0
    assert res_b.skipped_duplicates == 1
    assert res_b.campaign_total == 0
    a_rows = (await client.get(f"/api/leads?campaign_id={cid_a}")).json()
    b_rows = (await client.get(f"/api/leads?campaign_id={cid_b}")).json()
    assert len(a_rows) == 1 and len(b_rows) == 0


async def test_no_duplicate_company_rows(client):
    await _admin(client)
    cid = await _campaign(client, target=0)
    records = [_person("Ann", "Lee"), _person("Bob", "Roy")]  # same Acme Drones
    await _generate(cid, 5, records)
    import app.db as db_mod
    from sqlalchemy import func, select

    from app.leads.orm import Company

    async with db_mod.async_session() as session:
        n = (
            await session.execute(
                select(func.count(Company.id)).where(Company.name == "Acme Drones")
            )
        ).scalar_one()
    assert n == 1
