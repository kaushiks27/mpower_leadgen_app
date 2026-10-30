"""Deterministic monthly cost estimator — exact Decimal math, no floats.

Benchmark anchor: every flat-rate vendor cost below is quoted PER 6,000 emails/
month (the user's reference plan). For a different monthly email volume the flat
items scale **linearly pro-rata** from that anchor (locked default, RP Q1):

    item_cost = unit_per_6000 * emails / 6000

Mailbox cost is the exception — it is a STEP function, not linear. Each mailbox
can send at most 30 emails/day (locked, user note). Over a 30-calendar-day month
(locked default, RP Q2) that is 900 emails/mailbox/month, so:

    mailboxes = ceil(emails / (per_mailbox_per_day * sending_days))
    zapmail   = mailboxes * 3.9

Everything is `decimal.Decimal`; same inputs -> same outputs; line ordering is a
fixed list. No LLM, no float — this is load-bearing money math per CLAUDE.md.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# --- Anchor + caps ---------------------------------------------------------
BENCHMARK_EMAILS = Decimal(6000)  # all flat unit costs are quoted per this volume
PER_MAILBOX_PER_DAY = 30  # hard send cap per mailbox per day (user note)

# --- Vendor unit costs (USD) ----------------------------------------------
# Zapmail is per-mailbox/month; the rest are per-6,000-emails/month.
ZAPMAIL_PER_MAILBOX = Decimal("3.9")
APOLLO_PER_6K = Decimal("149")  # email + phone enrichment
APIFY_PER_6K = Decimal("49")  # lead scraping (actors)
VERIFY_PER_6K = Decimal("24")  # MillionVerifier email verification
CLAUDE_PER_6K = Decimal("30")  # AI icebreakers
INSTANTLY_PER_6K = Decimal("69")  # sending platform

_CENTS = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    """Quantize a money value to 2 dp, half-up (display precision, exact type)."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _ceil_div(numerator: int, denominator: int) -> int:
    """Exact integer ceiling division (no float). denominator must be > 0."""
    return -(-numerator // denominator)


def compute_estimate(emails: int, rate: Decimal, sending_days: int) -> dict:
    """Build the full cost estimate for `emails`/month at `rate` INR per USD.

    `sending_days` is the number of send-days assumed in a month (default 30),
    used only to derive the mailbox count. Returns a plain dict of Decimals +
    ints, ready for the Pydantic response model to stringify (strings preserve
    exact precision over the wire — never floats).
    """
    if emails < 1:
        raise ValueError("emails must be >= 1")
    if rate <= 0:
        raise ValueError("rate must be > 0")
    if sending_days < 1:
        raise ValueError("sending_days must be >= 1")

    emails_d = Decimal(emails)
    scale = emails_d / BENCHMARK_EMAILS  # linear pro-rata factor vs the 6k anchor

    # Mailbox count is a step function (ceil), not pro-rata.
    per_mailbox_month = PER_MAILBOX_PER_DAY * sending_days
    mailboxes = _ceil_div(emails, per_mailbox_month)
    zapmail_usd = ZAPMAIL_PER_MAILBOX * Decimal(mailboxes)

    lines: list[dict] = [
        {
            "key": "zapmail",
            "label": "Zapmail (mailboxes)",
            "detail": (
                f"{mailboxes} mailbox{'es' if mailboxes != 1 else ''} "
                f"× ${ZAPMAIL_PER_MAILBOX} · "
                f"{PER_MAILBOX_PER_DAY}/day × {sending_days} days"
            ),
            "usd": _q(zapmail_usd),
        },
        {
            "key": "apollo",
            "label": "Apollo (email + phone)",
            "detail": f"${APOLLO_PER_6K} per 6,000",
            "usd": _q(APOLLO_PER_6K * scale),
        },
        {
            "key": "apify",
            "label": "Apify (lead scraping)",
            "detail": f"${APIFY_PER_6K} per 6,000",
            "usd": _q(APIFY_PER_6K * scale),
        },
        {
            "key": "verify",
            "label": "MillionVerifier (email checks)",
            "detail": f"${VERIFY_PER_6K} per 6,000",
            "usd": _q(VERIFY_PER_6K * scale),
        },
        {
            "key": "claude",
            "label": "Claude (icebreakers)",
            "detail": f"${CLAUDE_PER_6K} per 6,000",
            "usd": _q(CLAUDE_PER_6K * scale),
        },
        {
            "key": "instantly",
            "label": "Instantly (sending)",
            "detail": f"${INSTANTLY_PER_6K} per 6,000",
            "usd": _q(INSTANTLY_PER_6K * scale),
        },
    ]

    # Sum the UNROUNDED parts is not what we want for an auditable line table —
    # the visible total must equal the sum of the visible (rounded) line USDs.
    total_usd = sum((line["usd"] for line in lines), Decimal(0))
    total_inr = _q(total_usd * rate)
    per_email_inr = _q(total_inr / emails_d)

    for line in lines:
        line["inr"] = _q(line["usd"] * rate)

    return {
        "emails": emails,
        "rate": rate,
        "sending_days": sending_days,
        "mailboxes": mailboxes,
        "per_mailbox_per_day": PER_MAILBOX_PER_DAY,
        "lines": lines,
        "total_usd": _q(total_usd),
        "total_inr": total_inr,
        "per_email_inr": per_email_inr,
        "per_lead_inr": per_email_inr,  # one email == one lead in this model
    }
