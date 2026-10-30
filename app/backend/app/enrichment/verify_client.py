"""Thin async MillionVerifier client + deterministic result mapping.

MillionVerifier v3 single-email check: `GET /api/v3/?api=KEY&email=...`. The JSON
carries a `result` (ok | catch_all | unknown | disposable | invalid) and a
`quality` hint. We map that to a stable `email_status` used across the app.

The map is the SSOT for "which leads can be pushed to Instantly": `valid`
(MillionVerifier `ok`) AND `catch_all` (a catch-all domain — accepts any address,
so a per-mailbox probe is impossible but the address is on the company's own
domain) are send-eligible. The leadgen post-enrich gate guarantees a surviving
lead's email domain matches the target company, so a `catch_all` is always
on-domain — never a wrong-company address. Everything else carries the
"unverified" tag and is excluded from the S-8 push. Mapping is pure +
deterministic (no LLM, no float) so the eligibility decision is reproducible.
"""

from __future__ import annotations

import httpx

_URL = "https://api.millionverifier.com/api/v3/"

# Stored lead.email_status values. SSOT — leads/router + frontend mirror these.
VALID = "valid"            # MillionVerifier "ok" → "SalesPath Sure"
CATCH_ALL = "catch_all"    # catch-all domain (on-company) → "SalesPath Likely"
OFF_DOMAIN = "off_domain"  # email domain ≠ company domain → "SalesPath No"
RISKY = "risky"            # legacy (pre-CATCH_ALL rows); no longer produced
INVALID = "invalid"
UNKNOWN = "unknown"
NO_EMAIL = "no_email"

# Send-eligible statuses (S-8 Instantly push + icebreaker gen). `catch_all` joins
# `valid` because the leadgen gate guarantees it is on the company's own domain.
ELIGIBLE_STATUSES = (VALID, CATCH_ALL)
# Back-compat single-value alias (still == "valid").
ELIGIBLE_STATUS = VALID


class VerifyError(RuntimeError):
    """Raised when the MillionVerifier call fails (auth, transport, bad body)."""


def map_result(result: str | None) -> str:
    """MillionVerifier `result` -> our email_status. Deterministic."""
    r = (result or "").strip().lower()
    if r == "ok":
        return VALID
    if r in {"catch_all", "catchall"}:
        return CATCH_ALL
    if r in {"invalid", "disposable"}:
        return INVALID
    # "unknown", "error", "" and anything unexpected -> unknown (not eligible).
    return UNKNOWN


def is_eligible(email_status: str | None) -> bool:
    """True for send-eligible emails: verified-deliverable OR on-domain catch-all."""
    return email_status in ELIGIBLE_STATUSES


async def verify_email(token: str, email: str, *, timeout: float = 30.0) -> str:
    """Verify one email, returning a mapped email_status. Raises VerifyError."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(_URL, params={"api": token, "email": email})
    except httpx.HTTPError as e:
        raise VerifyError(f"could not reach MillionVerifier: {e}") from e

    if resp.status_code >= 400:
        raise VerifyError(
            f"MillionVerifier returned {resp.status_code}: {resp.text[:300]}"
        )
    try:
        body = resp.json()
    except ValueError as e:
        raise VerifyError("MillionVerifier returned a non-JSON body") from e
    if not isinstance(body, dict):
        raise VerifyError("MillionVerifier returned an unexpected body")
    # An `error` field present without a result means the key/quota failed.
    if body.get("result") is None and body.get("error"):
        raise VerifyError(f"MillionVerifier error: {str(body.get('error'))[:200]}")
    return map_result(body.get("result"))
