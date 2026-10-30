"""Exact-math tests for the cost estimator — Decimal, deterministic, no floats."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.cost.calculator import compute_estimate


def test_default_scenario_6000_emails_rate_86():
    """Locked reference scenario: 6,000 emails, ₹86/USD, 30 send-days."""
    r = compute_estimate(emails=6000, rate=Decimal("86"), sending_days=30)

    # ceil(6000 / (30 * 30)) = ceil(6000/900) = ceil(6.66..) = 7 mailboxes
    assert r["mailboxes"] == 7
    by_key = {line["key"]: line for line in r["lines"]}

    assert by_key["zapmail"]["usd"] == Decimal("27.30")  # 7 × 3.9
    assert by_key["apollo"]["usd"] == Decimal("149.00")  # ×1 at the anchor
    assert by_key["apify"]["usd"] == Decimal("49.00")
    assert by_key["verify"]["usd"] == Decimal("24.00")
    assert by_key["claude"]["usd"] == Decimal("30.00")
    assert by_key["instantly"]["usd"] == Decimal("69.00")

    # Total = sum of the visible (rounded) line USDs.
    assert r["total_usd"] == Decimal("348.30")
    assert r["total_inr"] == Decimal("29953.80")  # 348.30 × 86
    # 29953.80 / 6000 = 4.9923 -> 4.99 (half-up, 2dp)
    assert r["per_email_inr"] == Decimal("4.99")
    assert r["per_lead_inr"] == r["per_email_inr"]


def test_flat_items_scale_linearly_mailbox_steps():
    """Doubling volume doubles flat items; mailboxes step via ceil, not pro-rata."""
    base = compute_estimate(emails=6000, rate=Decimal("86"), sending_days=30)
    dbl = compute_estimate(emails=12000, rate=Decimal("86"), sending_days=30)

    base_apollo = next(l for l in base["lines"] if l["key"] == "apollo")["usd"]
    dbl_apollo = next(l for l in dbl["lines"] if l["key"] == "apollo")["usd"]
    assert dbl_apollo == base_apollo * 2  # 149 -> 298, linear

    # ceil(12000/900) = ceil(13.33) = 14 mailboxes (step function)
    assert dbl["mailboxes"] == 14
    dbl_zap = next(l for l in dbl["lines"] if l["key"] == "zapmail")["usd"]
    assert dbl_zap == Decimal("54.60")  # 14 × 3.9


def test_mailbox_ceil_partial_bucket():
    """Even one email needs a full mailbox; ceil never rounds down."""
    r = compute_estimate(emails=1, rate=Decimal("86"), sending_days=30)
    assert r["mailboxes"] == 1


def test_sending_days_changes_mailbox_count():
    """Fewer send-days -> fewer emails per mailbox -> more mailboxes."""
    r22 = compute_estimate(emails=6000, rate=Decimal("86"), sending_days=22)
    # ceil(6000 / (30*22)) = ceil(6000/660) = ceil(9.09) = 10
    assert r22["mailboxes"] == 10


def test_rate_only_scales_inr_not_usd():
    """Changing the conversion rate must not move any USD figure."""
    a = compute_estimate(emails=6000, rate=Decimal("80"), sending_days=30)
    b = compute_estimate(emails=6000, rate=Decimal("90"), sending_days=30)
    assert a["total_usd"] == b["total_usd"]
    assert a["total_inr"] != b["total_inr"]
    assert b["total_inr"] == a["total_usd"] * Decimal("90")


def test_deterministic_same_input_same_output():
    """Same inputs -> identical output, including line ordering."""
    a = compute_estimate(emails=4321, rate=Decimal("83.5"), sending_days=30)
    b = compute_estimate(emails=4321, rate=Decimal("83.5"), sending_days=30)
    assert a == b
    assert [l["key"] for l in a["lines"]] == [
        "zapmail",
        "apollo",
        "apify",
        "verify",
        "claude",
        "instantly",
    ]


def test_outputs_are_exact_decimal_never_float():
    r = compute_estimate(emails=6000, rate=Decimal("86"), sending_days=30)
    assert isinstance(r["total_inr"], Decimal)
    for line in r["lines"]:
        assert isinstance(line["usd"], Decimal)
        assert isinstance(line["inr"], Decimal)


@pytest.mark.parametrize(
    "emails,rate,days",
    [(0, Decimal("86"), 30), (6000, Decimal("0"), 30), (6000, Decimal("86"), 0)],
)
def test_invalid_inputs_raise(emails, rate, days):
    with pytest.raises(ValueError):
        compute_estimate(emails=emails, rate=rate, sending_days=days)
