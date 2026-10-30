"""Pure-unit tests for the Generate-Leads engine — no DB, no network."""

from __future__ import annotations

from app.leadgen import membership, roles, sourcing, widen
from app.leadgen.service import roles_union


def test_expand_roles_dedup_and_order():
    out = roles.expand_roles(["Quality", "Product & Program"])
    # Order follows ROLE_GROUPS declaration order: Product & Program is declared
    # before Quality, so its titles come first regardless of selection order.
    assert out[0] == "Product Manager"
    assert "Quality Manager" in out
    # Deterministic + deduped: no duplicates, stable across calls.
    assert len(out) == len(set(t.lower() for t in out))
    assert roles.expand_roles(["Quality", "Product & Program"]) == out


def test_expand_roles_unknown_group_ignored():
    assert roles.expand_roles(["Nope", "Quality"]) == roles.expand_roles(["Quality"])
    assert roles.expand_roles([]) == []


def test_roles_union_dedups_case_insensitive():
    base = ["Buyer", "Procurement"]
    extra = ["buyer", "Category Manager"]
    out = roles_union(base, extra)
    assert out == ["Buyer", "Procurement", "Category Manager"]


def test_map_person_field_variants():
    raw = {
        "fullName": "Asha Rao",
        "profileUrl": "https://linkedin.com/in/asharao",
        "position": "Procurement Manager",
        "company_name": "DroneCo",
        "city": "Bengaluru",
    }
    p = sourcing.map_person(raw)
    assert p["first_name"] == "Asha" and p["last_name"] == "Rao"
    assert p["linkedin_url"].endswith("asharao")
    assert p["title"] == "Procurement Manager"
    assert p["company_name"] == "DroneCo"
    assert sourcing.map_person("nope") is None


def test_build_inputs_deterministic():
    a = sourcing.build_linkedin_input("DroneCo", ["Buyer", "CEO"], "India")
    b = sourcing.build_linkedin_input("DroneCo", ["Buyer", "CEO"], "India")
    assert a == b
    # REVIVED contract: anchored on currentJobTitles + Full+email; no `companyName`
    # (the actor ignores it). Without a LinkedIn URL → fuzzy searchQuery fallback.
    assert "companyName" not in a
    assert a["currentJobTitles"] == ["Buyer", "CEO"]
    assert a["profileScraperMode"] == "Full + email search"
    assert a["searchQuery"] == "DroneCo"
    assert a["locations"] == ["India"]
    # WITH a LinkedIn company URL → company-anchored via currentCompanies.
    c = sourcing.build_linkedin_input(
        "DroneCo", ["Buyer"], "India",
        li_url="https://www.linkedin.com/company/droneco",
    )
    assert c["currentCompanies"] == ["https://www.linkedin.com/company/droneco"]
    assert "searchQuery" not in c

    # company-employees: `maxEmployees` removed (caused HTTP 400); Full+email mode.
    ce = sourcing.build_company_employees_input(
        "https://www.linkedin.com/company/droneco", ["Buyer", "CEO"]
    )
    assert "maxEmployees" not in ce
    assert ce["companies"] == ["https://www.linkedin.com/company/droneco"]
    assert ce["jobTitles"] == ["Buyer", "CEO"]
    assert "email search" in ce["profileScraperMode"]

    # email-finder: bare domain + one decision-maker category.
    ef = sourcing.build_email_finder_input("www.dslrpros.com", "ceo_founder_owner", 15)
    assert ef == {"domain": "dslrpros.com", "decision_maker_category": "ceo_founder_owner",
                  "max_leads_to_find": 15}

    f = sourcing.build_fallback_input("DroneCo", ["Buyer", "buyer", "CEO"], "India")
    # title tokens lowercased + deduped + sorted (deterministic).
    assert f["contact_job_title"] == ["buyer", "ceo"]
    assert f["company_keywords"] == ["DroneCo"]  # no anchor domain → keyword fallback
    assert f["contact_location"] == ["india"]


def test_apollo_input_prefers_company_domain():
    """KI-26 fix: with an anchor domain, Apollo queries by company_domain (exact
    employer) — NOT the description-OR company_keywords (the bug)."""
    inp = sourcing.build_apollo_input("DSLRPros", "www.dslrpros.com", ["Buyer"], "USA")
    assert inp["company_domain"] == ["dslrpros.com"]
    assert "company_keywords" not in inp
    assert inp["contact_job_title"] == ["buyer"]


def test_map_person_extracts_employer_domain():
    p = sourcing.map_person({
        "name": "Asha Rao", "title": "Buyer",
        "organization": {"name": "DSLRPros", "primary_domain": "dslrpros.com"},
    })
    assert p["company_domain"] == "dslrpros.com"
    # email-only employer signal also resolves.
    p2 = sourcing.map_person({"name": "Bo Li", "email": "bo@dslrpros.com"})
    assert p2["company_domain"] == "dslrpros.com"


def test_pick_anchor_skips_social_and_picks_company_site():
    results = [
        {"url": "https://www.linkedin.com/company/dslrpros"},
        {"url": "https://en.wikipedia.org/wiki/Drones"},
        {"url": "https://www.dslrpros.com/about"},
        {"url": "https://dronefoo.com"},
    ]
    a = sourcing.pick_anchor(results)
    assert a["domain"] == "dslrpros.com"          # first non-social organic host
    assert a["website"].startswith("https://www.dslrpros.com")
    assert a["linkedin_url"].endswith("/company/dslrpros")


def test_membership_verdict():
    aliases = membership.make_aliases("DSLRPros", ["DSLR Pros"])
    # domain match → verified
    v, _ = membership.verdict(
        {"company_name": None, "company_domain": "dslrpros.com"},
        {"email": "x@mail.dslrpros.com"},
        anchor_domain="dslrpros.com", target_name="DSLRPros", aliases=aliases,
    )
    assert v == "verified"
    # name/alias match (spacing variant) → verified
    v2, _ = membership.verdict(
        {"company_name": "DSLR Pros LLC", "company_domain": ""},
        {}, anchor_domain="dslrpros.com", target_name="DSLRPros", aliases=aliases,
    )
    assert v2 == "verified"
    # unrelated company → mismatch (the KI-26 case: Continental for a DSLRPros run)
    v3, _ = membership.verdict(
        {"company_name": "Continental", "company_domain": "continental.com"},
        {}, anchor_domain="dslrpros.com", target_name="DSLRPros", aliases=aliases,
    )
    assert v3 == "mismatch"
    # no employer signal at all → mismatch (religious: positive match required)
    v4, _ = membership.verdict(
        {"company_name": None, "company_domain": ""},
        {}, anchor_domain="dslrpros.com", target_name="DSLRPros", aliases=aliases,
    )
    assert v4 == "mismatch"


def test_membership_registrable_collapses_subdomains():
    assert membership.registrable("https://mail.dslrpros.com/x") == "dslrpros.com"
    assert membership.registrable("www.foo.co.in") == "foo.co.in"


def test_widen_parse_defensive():
    assert widen.parse_titles('{"titles": ["Buyer", "buyer", "VP"]}') == ["Buyer", "VP"]
    assert widen.parse_titles("garbage no json") == []
    assert widen.parse_titles('{"nope": 1}') == []
    assert widen.parse_titles("") == []
