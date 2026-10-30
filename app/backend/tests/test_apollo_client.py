"""Pure-unit tests for the Apollo client mapping (no network)."""

from __future__ import annotations

from app.enrichment.apollo_client import build_match_payload, extract_person


def test_payload_only_includes_non_empty_hints():
    p = build_match_payload(
        {"first_name": "Mia", "last_name": "", "organization_name": "Acme", "email": ""}
    )
    assert p["reveal_personal_emails"] is True
    assert p["first_name"] == "Mia"
    assert p["organization_name"] == "Acme"
    assert "last_name" not in p  # empty dropped
    assert "email" not in p


def test_extract_person_pulls_email_and_phone():
    body = {
        "person": {
            "email": "mia@acme.com",
            "phone_numbers": [{"raw_number": "+1 555 0100"}],
            "headline": "Head of Procurement",
            "title": "VP Procurement",
        }
    }
    out = extract_person(body)
    assert out["email"] == "mia@acme.com"
    assert out["phone"] == "+1 555 0100"
    assert out["headline"] == "Head of Procurement"
    assert out["title"] == "VP Procurement"


def test_extract_person_handles_missing_person():
    assert extract_person({}) == {
        "email": None,
        "phone": None,
        "headline": None,
        "title": None,
    }


def test_extract_person_blank_email_becomes_none():
    out = extract_person({"person": {"email": "  "}})
    assert out["email"] is None
    assert out["phone"] is None
