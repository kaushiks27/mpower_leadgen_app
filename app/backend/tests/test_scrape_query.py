"""Pure Apify-input builder — deterministic, no I/O (S-5 / S-5d)."""

from __future__ import annotations

import pytest

from app.scraping.query import build_search_input, split_role_titles


def test_split_roles_splits_dedupes_sorts():
    out = split_role_titles(
        [
            "Procurement / Sourcing / Supply-chain",
            "Founder / CEO / CXO / Owner",
            "procurement",  # dup of a token above (case-insensitive)
        ]
    )
    assert out == sorted(out)  # deterministic order
    assert "procurement" in out and "sourcing" in out and "ceo" in out
    assert out.count("procurement") == 1  # de-duped


def test_split_roles_handles_blanks():
    assert split_role_titles(["", "  /  ", None]) == []


def test_build_input_maps_all_fields():
    inp = build_search_input(
        role_names=["Procurement / Sourcing"],
        geography="India",
        icp_keywords=["drone manufacturer, drone OEM"],
        fetch_count=5,
    )
    assert inp["fetch_count"] == 5
    assert inp["contact_job_title"] == ["procurement", "sourcing"]
    assert inp["contact_location"] == ["india"]  # lowercased for Apify enum
    # ICP value split on comma -> drone-anchored company keywords (S-5d)
    assert inp["company_keywords"] == ["drone manufacturer", "drone OEM"]


def test_global_geography_omits_location():
    inp = build_search_input(
        role_names=["Founder"], geography="Global", fetch_count=3
    )
    assert "contact_location" not in inp  # Global = search everywhere


def test_empty_targeting_omits_keys():
    inp = build_search_input(role_names=[], geography=None, fetch_count=2)
    assert inp == {"fetch_count": 2}


def test_fetch_count_must_be_positive():
    with pytest.raises(ValueError):
        build_search_input(role_names=[], geography=None, fetch_count=0)


def test_icp_keywords_split_on_comma_not_slash():
    """S-5d P0 fix: ICP keyword specs split on comma; '/' is NOT a separator
    (splitting it produced the generic 'Manufacturers' token that broke
    relevance). A '/' inside a keyword is kept verbatim."""
    inp = build_search_input(
        role_names=[],
        geography=None,
        icp_keywords=[
            "drone manufacturer, drone OEM",
            "drone distributor, drone reseller",
        ],
        fetch_count=4,
    )
    assert inp["company_keywords"] == [
        "drone manufacturer",
        "drone OEM",
        "drone distributor",
        "drone reseller",
    ]


def test_icp_keywords_dedupe_case_insensitively():
    inp = build_search_input(
        role_names=[],
        geography=None,
        icp_keywords=["drone OEM, UAV maker", "drone oem"],
        fetch_count=2,
    )
    assert inp["company_keywords"] == ["drone OEM", "UAV maker"]


def test_no_icp_omits_company_keywords():
    inp = build_search_input(
        role_names=["Founder"], geography="India", fetch_count=1
    )
    assert "company_keywords" not in inp  # ICP is the sole company signal


def test_deterministic_same_input_same_output():
    kwargs = dict(
        role_names=["B / A", "C"],
        geography="India",
        icp_keywords=["drone manufacturer, drone OEM"],
        fetch_count=5,
    )
    assert build_search_input(**kwargs) == build_search_input(**kwargs)
