"""Pure-unit tests for the MillionVerifier result mapping (no network).

This map is the SSOT for Instantly eligibility — only `valid` (MV `ok`) is
eligible; everything else is "unverified" and excluded from the S-8 push.
"""

from __future__ import annotations

import pytest

from app.enrichment.verify_client import is_eligible, map_result


@pytest.mark.parametrize(
    "result,expected",
    [
        ("ok", "valid"),
        ("OK", "valid"),
        ("catch_all", "catch_all"),
        ("catchall", "catch_all"),
        ("invalid", "invalid"),
        ("disposable", "invalid"),
        ("unknown", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
        ("totally_unexpected", "unknown"),
    ],
)
def test_map_result(result, expected):
    assert map_result(result) == expected


def test_valid_and_catch_all_are_eligible():
    # "SalesPath Sure" (valid) + on-domain "SalesPath Likely" (catch_all) are
    # send-eligible; everything else is not.
    assert is_eligible("valid") is True
    assert is_eligible("catch_all") is True
    for s in ("off_domain", "risky", "invalid", "unknown", "no_email", None):
        assert is_eligible(s) is False
