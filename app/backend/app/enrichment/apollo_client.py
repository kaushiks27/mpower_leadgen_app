"""Thin async Apollo People-Match client — network I/O isolated for testing.

Apollo's People Enrichment endpoint (`POST /v1/people/match`) takes identity
hints (name, company, LinkedIn URL, email) and returns the matched person with a
work email and, when revealed, phone numbers. Auth is the `X-Api-Key` header.

Isolated behind `match_person()` so `enrichment.service` is unit-tested with a
fake matcher (no live call, no credits). One credit = one match call.
"""

from __future__ import annotations

import httpx

_URL = "https://api.apollo.io/api/v1/people/match"


class ApolloError(RuntimeError):
    """Raised when the Apollo call fails (auth, transport, or bad body)."""


def build_match_payload(lead_hint: dict) -> dict:
    """Identity hints for one lead -> Apollo match request body.

    Pure (no I/O) so it is unit-tested directly. Only non-empty hints are sent.
    `reveal_personal_emails` asks Apollo to return the work email.
    """
    payload: dict = {"reveal_personal_emails": True}
    mapping = {
        "first_name": "first_name",
        "last_name": "last_name",
        "organization_name": "organization_name",
        "domain": "domain",
        "linkedin_url": "linkedin_url",
        "email": "email",
    }
    for src, dst in mapping.items():
        v = lead_hint.get(src)
        if isinstance(v, str) and v.strip():
            payload[dst] = v.strip()
    return payload


def extract_person(body: dict) -> dict:
    """Pull email + phone (+ a couple of icebreaker hints) from a match body.

    Defensive: Apollo field shapes are not contractually stable. Returns a dict
    with `email` / `phone` (None when absent) plus `headline`/`title` for S-7.
    """
    person = body.get("person") if isinstance(body, dict) else None
    if not isinstance(person, dict):
        return {"email": None, "phone": None, "headline": None, "title": None}

    email = person.get("email")
    if not (isinstance(email, str) and email.strip()):
        email = None

    phone = None
    nums = person.get("phone_numbers")
    if isinstance(nums, list):
        for n in nums:
            if isinstance(n, dict):
                raw = n.get("raw_number") or n.get("sanitized_number")
                if isinstance(raw, str) and raw.strip():
                    phone = raw.strip()
                    break
    if phone is None:
        raw = person.get("phone") or person.get("sanitized_phone")
        if isinstance(raw, str) and raw.strip():
            phone = raw.strip()

    return {
        "email": email.strip() if email else None,
        "phone": phone,
        "headline": (person.get("headline") or "").strip() or None,
        "title": (person.get("title") or "").strip() or None,
    }


async def match_person(
    token: str, lead_hint: dict, *, timeout: float = 30.0
) -> dict:
    """Match one person and return `extract_person(...)`. Raises ApolloError."""
    payload = build_match_payload(lead_hint)
    headers = {"X-Api-Key": token, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(_URL, headers=headers, json=payload)
    except httpx.HTTPError as e:
        raise ApolloError(f"could not reach Apollo: {e}") from e

    if resp.status_code >= 400:
        raise ApolloError(f"Apollo returned {resp.status_code}: {resp.text[:300]}")
    try:
        body = resp.json()
    except ValueError as e:
        raise ApolloError("Apollo returned a non-JSON body") from e
    if not isinstance(body, dict):
        raise ApolloError("Apollo returned an unexpected (non-object) body")
    return extract_person(body)
