"""Pure dedup + normalization — deterministic, tier-prefixed, format-robust."""

from __future__ import annotations

import pytest

from app.leads.dedup import dedup_key
from app.suppression.normalize import normalize_email, normalize_linkedin


def test_normalize_email_case_and_whitespace():
    assert normalize_email("  John@X.com ") == "john@x.com"
    assert normalize_email("") is None
    assert normalize_email(None) is None


def test_normalize_linkedin_strips_scheme_host_query_trailing_slash():
    a = normalize_linkedin("https://www.linkedin.com/in/aarav-mehta")
    b = normalize_linkedin("http://LinkedIn.com/in/Aarav-Mehta/")
    c = normalize_linkedin("linkedin.com/in/aarav-mehta?utm=x#frag")
    assert a == b == c == "linkedin.com/in/aarav-mehta"


def test_normalize_linkedin_empty():
    assert normalize_linkedin(None) is None
    assert normalize_linkedin("   ") is None


def test_dedup_precedence_linkedin_wins():
    # Same LinkedIn but different email -> same key (LinkedIn tier wins).
    k1 = dedup_key(
        first_name="A", last_name="B", email="a@x.com",
        linkedin_url="https://linkedin.com/in/ab", company_name="X",
    )
    k2 = dedup_key(
        first_name="A", last_name="B", email="different@y.com",
        linkedin_url="http://www.LinkedIn.com/in/ab/", company_name="Y",
    )
    assert k1 == k2
    assert k1.startswith("li:")


def test_dedup_email_tier_when_no_linkedin():
    k = dedup_key(
        first_name="A", last_name="B", email="A@X.com",
        linkedin_url=None, company_name="Acme",
    )
    assert k.startswith("em:")
    # case-insensitive email
    k2 = dedup_key(
        first_name="Z", last_name="Q", email="a@x.com",
        linkedin_url=None, company_name="Other",
    )
    assert k == k2


def test_dedup_name_company_tier_last():
    k = dedup_key(
        first_name="Jane", last_name="Doe", email=None,
        linkedin_url=None, company_name="Acme Inc",
    )
    assert k.startswith("nc:")
    # whitespace/case normalized
    k2 = dedup_key(
        first_name="  jane ", last_name="DOE", email=None,
        linkedin_url=None, company_name="acme   inc",
    )
    assert k == k2


def test_different_tiers_never_collide():
    li = dedup_key(first_name="A", last_name="B", email=None,
                   linkedin_url="linkedin.com/in/x", company_name=None)
    em = dedup_key(first_name="A", last_name="B", email="x@y.com",
                   linkedin_url=None, company_name=None)
    nc = dedup_key(first_name="A", last_name="B", email=None,
                   linkedin_url=None, company_name="C")
    assert len({li, em, nc}) == 3


def test_no_identifier_raises():
    with pytest.raises(ValueError):
        dedup_key(first_name="Only", last_name="Name", email=None,
                  linkedin_url=None, company_name=None)


def test_deterministic_same_input_same_key():
    args = dict(first_name="A", last_name="B", email="a@b.com",
                linkedin_url=None, company_name="C")
    assert dedup_key(**args) == dedup_key(**args)
