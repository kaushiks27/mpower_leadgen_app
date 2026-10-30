"""Stage-6 company-contact enrichment (S-MS1) — module-local (OP #11).

Native discovery harvests phone well (70–100%) but email ~0% (smoke/RESULTS.md), so
Apollo + MillionVerifier is the PRIMARY email source. For an eligible (Sure/Likely)
customer missing a contact we, by DOMAIN only:

  1. Apollo organizations/enrich  → authoritative company PHONE.
  2. Apollo people_search (domain-scoped) → first work-email person → bulk_match →
     a work EMAIL. The match's company domain MUST equal the target domain (registrable
     compare) or the email is rejected — this is the S1 off-company-contamination gate.
  3. MillionVerifier verifies the chosen email → keep only valid / catch_all; an
     invalid/unknown verdict never lands an address (only the flag is recorded).

We store ONE company email + ONE phone (no named decision-maker is persisted — the
person's name/title is dropped; only their work email becomes the company email).

Own copy of the Apollo + MillionVerifier HTTP rather than importing app.leadgen /
app.enrichment (feature→feature is disallowed). Pure mappers are split out so they
unit-test with no network; determinism: first-match wins, deterministic ordering, no
float, the LLM decides nothing here.
"""

from __future__ import annotations

import httpx

from app.customers.service import normalize_domain

_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
_BULK_MATCH_URL = "https://api.apollo.io/api/v1/people/bulk_match"
_ORG_ENRICH_URL = "https://api.apollo.io/api/v1/organizations/enrich"
_MV_URL = "https://api.millionverifier.com/api/v3/"

# Seniorities covering a company's decision-makers (the email just needs to be a real
# work address on the company's own domain — title is not stored).
_SENIORITIES = ["owner", "founder", "c_suite", "vp", "head", "director", "manager"]

# MillionVerifier result -> our email_quality (mirrors enrichment.verify_client SSOT).
_VALID = "valid"
_CATCH_ALL = "catch_all"
_INVALID = "invalid"
_UNKNOWN = "unknown"
_ELIGIBLE = (_VALID, _CATCH_ALL)


class EnrichError(RuntimeError):
    """Raised when an Apollo / MillionVerifier call fails (auth, transport, body)."""


# --- pure helpers (no network) ----------------------------------------------
def _s(d: dict, *keys: str) -> str | None:
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):  # e.g. primary_phone: {number: ...}
            inner = _s(v, "number", "sanitized_number", "raw_number")
            if inner:
                return inner
    return None


def org_phone(body: dict) -> str | None:
    """organizations/enrich body → a company phone string (or None)."""
    o = body.get("organization") if isinstance(body, dict) else None
    if not isinstance(o, dict):
        return None
    return _s(o, "sanitized_phone", "phone", "primary_phone")


def pick_person(people: list) -> dict | None:
    """First person with a work email (has_email) — else the first person. Returns the
    raw Apollo person dict (carries `id` for bulk_match), or None."""
    rows = [p for p in (people or []) if isinstance(p, dict)]
    for p in rows:
        if p.get("has_email") and _s(p, "id"):
            return p
    for p in rows:
        if _s(p, "id"):
            return p
    return None


def match_email(match: dict, target_domain: str) -> str | None:
    """bulk_match row → a work email, BUT only if its company domain matches the target
    (off-company gate). Deterministic registrable compare. Returns None otherwise."""
    if not isinstance(match, dict):
        return None
    email = _s(match, "email")
    if not email or "@" not in email:
        return None
    org = match.get("organization") if isinstance(match.get("organization"), dict) else {}
    cand_dom = _s(org, "primary_domain", "domain")
    if not cand_dom:
        # fall back to the email's own domain
        cand_dom = email.rsplit("@", 1)[-1]
    if normalize_domain(cand_dom) != normalize_domain(target_domain):
        return None
    return email.lower()


def map_mv(result: str | None) -> str:
    """MillionVerifier `result` → our email_quality. Deterministic."""
    r = (result or "").strip().lower()
    if r == "ok":
        return _VALID
    if r in {"catch_all", "catchall"}:
        return _CATCH_ALL
    if r in {"invalid", "disposable"}:
        return _INVALID
    return _UNKNOWN


# --- thin async clients -----------------------------------------------------
async def _apollo_get(token: str, url: str, params: dict, timeout: float) -> dict:
    headers = {"X-Api-Key": token, "Content-Type": "application/json", "Cache-Control": "no-cache"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(url, headers=headers, params=params)
    except httpx.HTTPError as e:
        raise EnrichError(f"could not reach Apollo: {e}") from e
    if r.status_code >= 400:
        raise EnrichError(f"apollo {url.rsplit('/', 1)[-1]} -> {r.status_code}: {r.text[:200]}")
    try:
        out = r.json()
    except ValueError as e:
        raise EnrichError("apollo non-JSON body") from e
    return out if isinstance(out, dict) else {}


async def _apollo_post(token: str, url: str, *, params=None, body=None, timeout: float) -> dict:
    headers = {"X-Api-Key": token, "Content-Type": "application/json", "Cache-Control": "no-cache"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, headers=headers, params=params or {}, json=body or {})
    except httpx.HTTPError as e:
        raise EnrichError(f"could not reach Apollo: {e}") from e
    if r.status_code >= 400:
        raise EnrichError(f"apollo {url.rsplit('/', 1)[-1]} -> {r.status_code}: {r.text[:200]}")
    try:
        out = r.json()
    except ValueError as e:
        raise EnrichError("apollo non-JSON body") from e
    return out if isinstance(out, dict) else {}


async def _mv_verify(token: str, email: str, timeout: float) -> str:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(_MV_URL, params={"api": token, "email": email})
    except httpx.HTTPError:
        return _UNKNOWN
    if r.status_code >= 400:
        return _UNKNOWN
    try:
        body = r.json()
    except ValueError:
        return _UNKNOWN
    if not isinstance(body, dict):
        return _UNKNOWN
    return map_mv(body.get("result"))


# --- orchestration ----------------------------------------------------------
async def enrich_contact(
    apollo_token: str | None,
    mv_token: str | None,
    *,
    domain: str,
    country: str | None = None,
    per_page: int = 5,
    timeout: float = 60.0,
) -> dict:
    """Enrich ONE company by domain → {"phone", "email", "email_quality"}.

    Any single sub-call failing degrades to a blank for that field (never raises) —
    the sync job must continue across companies. Email is only ever returned when it
    is on the company's own domain AND MillionVerifier-graded valid/catch_all.
    """
    out: dict = {"phone": None, "email": None, "email_quality": None}
    dom = normalize_domain(domain)
    if not dom or not apollo_token:
        return out

    # 1) company phone (Apollo org enrich)
    try:
        org_body = await _apollo_get(apollo_token, _ORG_ENRICH_URL, {"domain": dom}, timeout)
        out["phone"] = org_phone(org_body)
    except EnrichError:
        out["phone"] = None

    # 2) a work email on the company's own domain (people_search → bulk_match)
    email: str | None = None
    try:
        body: dict = {
            "q_organization_domains_list": [dom],
            "person_seniorities": list(_SENIORITIES),
            "per_page": max(1, min(25, int(per_page))),
            "page": 1,
        }
        loc = (country or "").strip()
        if loc and loc.lower() not in {"global", "worldwide"}:
            body["person_locations"] = [loc]
        search = await _apollo_post(apollo_token, _SEARCH_URL, body=body, timeout=timeout)
        person = pick_person(search.get("people") or [])
        if person is not None:
            match_out = await _apollo_post(
                apollo_token, _BULK_MATCH_URL,
                params={"reveal_personal_emails": "false"},
                body={"details": [{"id": _s(person, "id")}]}, timeout=timeout,
            )
            matches = match_out.get("matches") or []
            if matches and isinstance(matches[0], dict):
                email = match_email(matches[0], dom)
    except EnrichError:
        email = None

    # 3) verify the email — keep only deliverable / on-domain catch-all
    if email and mv_token:
        quality = await _mv_verify(mv_token, email, timeout)
        if quality in _ELIGIBLE:
            out["email"] = email
            out["email_quality"] = quality
        else:
            out["email_quality"] = quality  # flag only, no address stored
    elif email and not mv_token:
        # No verifier configured → cannot guarantee deliverability; record unverified.
        out["email_quality"] = _UNKNOWN
    # Mark the attempt: a Stage-6 pass always yields a verdict (even "nothing found")
    # so the row is never re-enriched / re-charged on the next Sync.
    if out["email_quality"] is None:
        out["email_quality"] = _UNKNOWN
    return out
