"""Pure-unit tests for the Apollo-native sourcing module + the new map_person
record shapes (harvest, snipercoder). Doc-grounded sample records, no network."""

from __future__ import annotations

from app.leadgen import apollo_native as A
from app.leadgen import sourcing


# --- search_input -----------------------------------------------------------
def test_search_input_domain_scoped_and_deterministic():
    a = A.search_input("www.dslrpros.com", ["Buyer", "buyer", "CEO"], "India", 25)
    b = A.search_input("www.dslrpros.com", ["Buyer", "buyer", "CEO"], "India", 25)
    assert a == b                                  # same input → same output
    assert a["q_organization_domains_list"] == ["dslrpros.com"]
    assert a["person_titles"] == ["Buyer", "CEO"]  # deduped (case-insensitive) + sorted
    assert a["person_seniorities"] == A.SENIORITIES
    assert a["person_locations"] == ["India"]
    assert a["per_page"] == 25 and a["page"] == 1


def test_search_input_clamps_and_drops_global():
    big = A.search_input("x.com", [], "global", 500)
    assert big["per_page"] == 100          # clamped to 100
    assert "person_locations" not in big   # "global" dropped
    assert "person_titles" not in big      # no titles → key omitted


def test_categories_for_groups():
    assert A.categories_for_groups(["Executive & Founder", "Procurement & Sourcing"]) == [
        "ceo_founder_owner", "director_head_president"
    ]
    assert A.categories_for_groups([]) == ["director_head_president"]  # safe default


# --- map_search -------------------------------------------------------------
def test_map_search_carries_id_and_has_email():
    rec = {
        "id": "000000000000000000000001",
        "first_name": "Jane",
        "last_name_obfuscated": "D***e",
        "title": "Director of Services",
        "has_email": True,
        "organization": {"name": "DSLR Pros"},
    }
    p = A.map_search(rec)
    assert p["first_name"] == "Jane"
    assert p["last_name"] == "D***e"          # obfuscated until enriched
    assert p["apollo_id"] == "000000000000000000000001"
    assert p["has_email"] is True
    assert p["organization_name"] == "DSLR Pros"
    assert p["_engine"] == "apollo"
    # The membership gate sees a real org name → name-match passes (domain-scoped).
    person = sourcing.map_person(p)
    assert person["company_name"] == "DSLR Pros"


# --- map_match --------------------------------------------------------------
def test_map_match_pulls_email_phone_domain():
    rec = {
        "first_name": "Jane", "last_name": "Doe",
        "email": "jane.doe@dslrpros.com", "email_status": "verified",
        "linkedin_url": "http://www.linkedin.com/in/janedoe",
        "title": "Director of Services",
        "phone_numbers": [{"sanitized_number": "+15555550123", "raw_number": "(555) 555-0123"}],
        "city": "Los Angeles", "state": "California", "country": "United States",
        "organization": {"name": "DSLR Pros", "primary_domain": "dslrpros.com"},
    }
    m = A.map_match(rec)
    assert m["email"] == "jane.doe@dslrpros.com"
    assert m["email_status"] == "verified"
    assert m["phone"] == "+15555550123"
    assert m["company_domain"] == "dslrpros.com"
    assert m["location"] == "Los Angeles, California, United States"


def test_map_match_domain_from_employment_history_when_org_blank():
    rec = {
        "first_name": "A", "last_name": "B", "email": "a@x.com",
        "organization": {},
        "employment_history": [
            {"current": False, "organization_domain": "old.com"},
            {"current": True, "organization_domain": "mail.acme.com"},
        ],
    }
    assert A.map_match(rec)["company_domain"] == "acme.com"


def test_map_match_handles_null_and_nondict():
    assert A.map_match(None) == {}
    empty = A.map_match({})
    assert empty["email"] is None and empty["phone"] is None


# --- map_org ----------------------------------------------------------------
def test_map_org():
    body = {"organization": {
        "name": "DSLR Pros", "primary_domain": "dslrpros.com",
        "linkedin_url": "http://www.linkedin.com/company/dslrpros",
    }}
    o = A.map_org(body)
    assert o == {"name": "DSLR Pros", "domain": "dslrpros.com",
                 "linkedin_url": "http://www.linkedin.com/company/dslrpros"}
    assert A.map_org({})["domain"] == ""


# --- map_person: NEW engine shapes -----------------------------------------
def test_map_person_snipercoder_shape_with_phone():
    """snipercoder email-finder NN_-prefixed keys → email + phone + employer domain."""
    raw = {
        "01_Name": "John Doe", "02_First_name": "John", "03_Last_name": "Doe",
        "04_Email": "john.doe@dslrpros.com", "05_Phone_number": "+15555550123",
        "06_Linkedin_url": "http://www.linkedin.com/in/johndoe",
        "07_Title": "Chief Financial Officer", "16_Company_name": "DSLR Pros",
        "17_Query_domain": "dslrpros.com",
    }
    p = sourcing.map_person(raw)
    assert p["first_name"] == "John" and p["last_name"] == "Doe"
    assert p["email"] == "john.doe@dslrpros.com"
    assert p["phone"] == "+15555550123"
    assert p["title"] == "Chief Financial Officer"
    assert p["company_name"] == "DSLR Pros"
    assert p["company_domain"] == "dslrpros.com"   # from 17_Query_domain


def test_map_person_harvest_shape_currentposition_and_emails_list():
    """harvestapi: employer in currentPosition LIST, email in emails[], nested location."""
    raw = {
        "firstName": "Pat", "lastName": "Sample",
        "headline": "Logistics and Procurement Manager",
        "linkedinUrl": "http://www.linkedin.com/in/pat-sample-0000",
        "emails": [{"email": "pat.sample@draganfly.com"}],
        "currentPosition": [{"companyName": "Draganfly Inc."}],
        "location": {"parsed": {"city": "Saskatoon", "country": "Canada"}},
    }
    p = sourcing.map_person(raw)
    assert p["first_name"] == "Pat" and p["last_name"] == "Sample"
    assert p["email"] == "pat.sample@draganfly.com"
    assert p["title"] == "Logistics and Procurement Manager"
    assert p["company_name"] == "Draganfly Inc."
    assert p["location"] == "Saskatoon, Canada"


def test_map_person_harvest_emails_list_of_strings():
    raw = {"firstName": "X", "lastName": "Y", "emails": ["x@acme.com"],
           "experience": [{"companyName": "Acme"}]}
    p = sourcing.map_person(raw)
    assert p["email"] == "x@acme.com"
    assert p["company_name"] == "Acme"
