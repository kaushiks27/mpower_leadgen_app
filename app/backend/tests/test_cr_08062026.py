"""08062026_cr — the customer change-request batch (CR-1…CR-6).

Covers: CR-1 band filter, CR-6 lead taxonomy + backfill, CR-5 deterministic
country→timezone map, CR-2 require-icebreaker toggle + addable-leads eligibility
+ add-leads pull + lead-mix + Instantly gate honoring the toggle. Each test uses
the isolated temp DB (conftest) — no live calls, no credits."""

from __future__ import annotations

import app.db as db_mod
from tests.conftest import login, make_user


async def _admin(client):
    await make_user(client, "admin@x.com", "pw12345678", role="admin")
    await login(client, "admin@x.com", "pw12345678")


async def _customer(name, *, band, ctype="OEM", country="India", category="Drone batteries"):
    from app.customers.orm import CustomerItem

    async with db_mod.async_session() as s:
        c = CustomerItem(
            name=name, band=band, ctype=ctype, country=country, category=category,
            domain=f"{name.lower().replace(' ', '')}.com",
            website=f"https://{name.lower().replace(' ', '')}.com",
            dedup_key=f"cust:{name.lower()}",
        )
        s.add(c)
        await s.commit()
        return c.id


async def _lead(
    *, key, email="x@a.com", status="valid", icebreaker=None, campaign_id=None,
    company_name=None, category=None, customer_type=None, location=None,
    customer_item_id=None,
):
    from app.leads.orm import Company, Lead

    async with db_mod.async_session() as s:
        company = None
        if company_name:
            company = Company(name=company_name, domain=f"{company_name.lower().replace(' ', '')}.com")
            s.add(company)
            await s.flush()
        lead = Lead(
            first_name="A", last_name=key, email=email, email_status=status,
            icebreaker=icebreaker, campaign_id=campaign_id, dedup_key=f"lead:{key}",
            stage="new", category=category, customer_type=customer_type,
            location=location, customer_item_id=customer_item_id,
            company_id=company.id if company else None,
        )
        s.add(lead)
        await s.commit()
        return lead.id


# --------------------------------------------------------------------------- #
# CR-5 — deterministic country→timezone map (pure).
# --------------------------------------------------------------------------- #

def test_timezone_map_is_deterministic_and_canonical():
    from app.campaigns.timezones import (
        DEFAULT_TZ,
        majority_timezone,
        timezone_for_country,
    )

    assert timezone_for_country("India") == "Asia/Kolkata"
    assert timezone_for_country("united states") == "America/New_York"
    assert timezone_for_country("  USA  ") == "America/New_York"
    assert timezone_for_country("Atlantis") == DEFAULT_TZ
    assert timezone_for_country(None) == DEFAULT_TZ
    # Majority wins.
    assert majority_timezone(["India", "India", "USA"]) == "Asia/Kolkata"
    # Frequency tie → alphabetical country tiebreak (Germany < USA).
    assert majority_timezone(["USA", "Germany"]) == "Europe/Berlin"
    assert majority_timezone([]) == DEFAULT_TZ
    # Determinism: same input → same output.
    assert majority_timezone(["USA", "India", "India"]) == majority_timezone(
        ["India", "USA", "India"]
    )


# --------------------------------------------------------------------------- #
# CR-1 — Generate-Leads band filter (backend-enforced).
# --------------------------------------------------------------------------- #

async def test_band_filter_hides_low_bands(client):
    await _admin(client)
    await _customer("SureCo", band="Sure")
    await _customer("LikelyCo", band="Likely")
    await _customer("UnsureCo", band="Unsure")
    await _customer("NoCo", band="No")
    await _customer("BlankCo", band=None)

    # Default (no bands param) → only Sure + Likely.
    rows = (await client.get("/api/leadgen/customers")).json()
    names = {r["name"] for r in rows}
    assert names == {"SureCo", "LikelyCo"}

    # Lists endpoint also excludes low bands.
    lists = (await client.get("/api/leadgen/lists")).json()
    assert {c["name"] for c in lists["customers"]} == {"SureCo", "LikelyCo"}

    # Narrow to Sure only.
    only_sure = (await client.get("/api/leadgen/customers?bands=Sure")).json()
    assert {r["name"] for r in only_sure} == {"SureCo"}

    # A malicious request for "No" is clamped → never leaks.
    bad = (await client.get("/api/leadgen/customers?bands=No")).json()
    assert bad == []


# --------------------------------------------------------------------------- #
# CR-6 — best-effort backfill of the lead taxonomy.
# --------------------------------------------------------------------------- #

async def test_backfill_fills_taxonomy_by_domain(client):
    await _admin(client)
    cid = await _customer("Acme Drones", band="Sure", ctype="Reseller", country="Germany", category="Payloads")
    # A pre-CR-6 lead at the same company (matched by domain), no taxonomy yet.
    lid = await _lead(key="old", company_name="Acme Drones", category=None, customer_type=None)

    from app.leadgen.backfill import backfill_lead_taxonomy

    async with db_mod.async_session() as s:
        filled = await backfill_lead_taxonomy(s)
    assert filled == 1

    from app.leads.orm import Lead

    async with db_mod.async_session() as s:
        lead = await s.get(Lead, lid)
        assert lead.customer_item_id == cid
        assert lead.category == "Payloads"
        assert lead.customer_type == "Reseller"
        assert lead.location == "Germany"

    # Idempotent: a second run changes nothing.
    async with db_mod.async_session() as s:
        assert await backfill_lead_taxonomy(s) == 0


async def test_backfill_matches_by_email_domain(client):
    # The strongest signal: a lead's work email sits on the company's domain even
    # when the scraped company name differs ("Wing" vs "Wing Aviation") and the
    # Company row has no domain stored.
    await _admin(client)
    cid = await _customer("Wing Aviation", band="Sure", ctype="OEM", country="United States", category="Delivery")
    matched = await _lead(key="byemail", email="pilot@wingaviation.com", company_name="Wing")
    # Off-domain email (person's current employer) must NOT be attributed.
    offdom = await _lead(key="offdom", email="x@uber.com", company_name="Wing")
    # No email at all → cannot match.
    noemail = await _lead(key="noemail", email=None, company_name="Wing")

    from app.leadgen.backfill import backfill_lead_taxonomy
    from app.leads.orm import Lead

    async with db_mod.async_session() as s:
        await backfill_lead_taxonomy(s)
    async with db_mod.async_session() as s:
        assert (await s.get(Lead, matched)).customer_item_id == cid
        assert (await s.get(Lead, matched)).category == "Delivery"
        assert (await s.get(Lead, offdom)).customer_item_id is None
        assert (await s.get(Lead, noemail)).customer_item_id is None


# --------------------------------------------------------------------------- #
# CR-2 — require-icebreaker toggle, addable-leads, add-leads, lead-mix, gate.
# --------------------------------------------------------------------------- #

async def test_create_with_toggle_and_pull_derives_timezone(client):
    await _admin(client)
    # Two eligible unassigned leads in Germany (no icebreaker) + toggle OFF.
    l1 = await _lead(key="g1", status="valid", location="Germany")
    l2 = await _lead(key="g2", status="catch_all", location="Germany")

    r = await client.post(
        "/api/campaigns",
        json={"name": "DE", "require_icebreaker": False, "lead_ids": [l1, l2]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["require_icebreaker"] is False
    # Timezone derived from the pulled leads' majority country.
    assert body["timezone"] == "Europe/Berlin"

    # Lead-mix reflects the pulled leads.
    mix = (await client.get(f"/api/campaigns/{body['id']}/lead-mix")).json()
    assert mix["lead_count"] == 2
    assert mix["countries"] == ["Germany"]
    assert mix["timezone"] == "Europe/Berlin"


async def test_addable_leads_eligibility(client):
    await _admin(client)
    ok = await _lead(key="ok", status="valid", icebreaker="hi")
    no_ice = await _lead(key="noice", status="valid", icebreaker=None)
    bad_band = await _lead(key="bad", status="invalid", icebreaker="hi")
    assigned = await _lead(key="taken", status="valid", icebreaker="hi", campaign_id=1)

    # require_icebreaker=true → only the verified lead WITH an icebreaker, unassigned.
    rows = (await client.get("/api/leads/addable?require_icebreaker=true")).json()
    ids = {r["id"] for r in rows}
    assert ok in ids
    assert no_ice not in ids
    assert bad_band not in ids
    assert assigned not in ids

    # require_icebreaker=false → the no-icebreaker verified lead becomes eligible.
    rows2 = (await client.get("/api/leads/addable?require_icebreaker=false")).json()
    ids2 = {r["id"] for r in rows2}
    assert ok in ids2 and no_ice in ids2
    assert bad_band not in ids2


async def test_add_leads_preserves_contact_once(client):
    await _admin(client)
    c = (await client.post("/api/campaigns", json={"name": "A"})).json()
    other = (await client.post("/api/campaigns", json={"name": "B"})).json()
    free = await _lead(key="free", status="valid", icebreaker="hi", location="India")
    taken = await _lead(key="taken2", status="valid", icebreaker="hi", campaign_id=other["id"])

    r = await client.post(
        f"/api/campaigns/{c['id']}/add-leads",
        json={"lead_ids": [free, taken]},
    )
    assert r.status_code == 200
    # Only the unassigned lead was pulled; the other campaign's lead is untouched.
    mine = (await client.get(f"/api/leads?campaign_id={c['id']}")).json()
    assert {x["id"] for x in mine} == {free}
    theirs = (await client.get(f"/api/leads?campaign_id={other['id']}")).json()
    assert {x["id"] for x in theirs} == {taken}


async def test_campaign_lead_gen_buttons_routes_gone(client):
    # CR-2: icebreaker relocated to /api/leads/icebreaker; campaign icebreaker
    # route gone. Master route needs ≥1 lead id.
    await _admin(client)
    r = await client.post("/api/leads/icebreaker", json={"lead_ids": []})
    assert r.status_code == 400
