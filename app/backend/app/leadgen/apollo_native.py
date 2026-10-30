"""Apollo-native sourcing client for Generate-Leads (module-local, OP #11).

Three Apollo surfaces, validated live 2026-06-07 (see the sandbox under
`directives/06062026_scrape_gen2/all_new_lead_gen/`):

  * `org_enrich(domain)`        — FREE-of-discovery anchor: canonical domain +
                                  LinkedIn company URL + org name. Fixes the
                                  Google anchor gap (e.g. Garuda).
  * `people_search(...)`        — FREE people discovery, domain-scoped
                                  (`q_organization_domains_list`). Over-fetch.
  * `bulk_match(ids|hints)`     — enrich up to 10/call → verified WORK email +
                                  linkedin + phone + employer domain.

Auth is the `X-Api-Key` header. Pure input builders + output mappers are split
out so they unit-test with no network. Determinism: title/seniority lists are
deduped + sorted; counts are ints; the LLM never decides anything here.
"""

from __future__ import annotations

import httpx

from app.leadgen import membership

SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
BULK_MATCH_URL = "https://api.apollo.io/api/v1/people/bulk_match"
ORG_ENRICH_URL = "https://api.apollo.io/api/v1/organizations/enrich"

# Seniorities covering mPower decision-makers (broad; titles + domain narrow it).
SENIORITIES = ["owner", "founder", "c_suite", "vp", "head", "director", "manager"]

# mPower role-group → snipercoder decision_maker_category (deterministic).
SNIPER_CATEGORY_BY_GROUP = {
    "Executive & Founder": "ceo_founder_owner",
    "Procurement & Sourcing": "director_head_president",
    "Supply Chain & Operations": "director_head_president",
    "Engineering & R&D": "director_head_president",
    "Product & Program": "manager_entry_intern",
    "Quality": "manager_entry_intern",
}


class ApolloNativeError(RuntimeError):
    """Raised when an Apollo-native call fails (auth, transport, bad body)."""


# --- pure input builders ----------------------------------------------------
def search_input(domain: str | None, titles: list[str], country: str | None, per_page: int) -> dict:
    """People-search body. Domain-scoped is the membership lever (near-zero leak)."""
    inp: dict = {
        "include_similar_titles": True,
        "person_seniorities": list(SENIORITIES),
        "per_page": max(1, min(100, int(per_page))),
        "page": 1,
    }
    seen: set[str] = set()
    t: list[str] = []
    for x in titles or []:
        if x and x.strip() and x.strip().lower() not in seen:
            seen.add(x.strip().lower())
            t.append(x.strip())
    t.sort(key=str.lower)
    if t:
        inp["person_titles"] = t
    d = membership.registrable(domain)
    if d:
        inp["q_organization_domains_list"] = [d]
    loc = (country or "").strip()
    if loc and loc.lower() not in {"global", "worldwide"}:
        inp["person_locations"] = [loc]
    return inp


def categories_for_groups(role_groups: list[str]) -> list[str]:
    """Distinct, ordered snipercoder categories implied by the selected groups."""
    out: list[str] = []
    for g in role_groups or []:
        cat = SNIPER_CATEGORY_BY_GROUP.get(g)
        if cat and cat not in out:
            out.append(cat)
    return out or ["director_head_president"]


# --- pure output mappers ----------------------------------------------------
def _s(rec: dict, *keys: str) -> str | None:
    for k in keys:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def map_search(rec: dict) -> dict:
    """Free-search row → a raw-lead dict the app's `map_person` understands.

    Carries `apollo_id` + `has_email` so stage-5 bulk_match can enrich it, and
    `organization_name` so the membership gate passes (search is domain-scoped).
    Search rows have NO email / linkedin / full last name — enrichment fills them.
    """
    org = rec.get("organization") if isinstance(rec.get("organization"), dict) else {}
    return {
        "first_name": _s(rec, "first_name") or "",
        "last_name": _s(rec, "last_name", "last_name_obfuscated") or "",
        "title": _s(rec, "title"),
        "organization_name": _s(org, "name"),
        "apollo_id": _s(rec, "id"),
        "has_email": bool(rec.get("has_email")),
        "_engine": "apollo",
    }


def map_match(rec: dict) -> dict:
    """bulk_match row → {email, phone, linkedin_url, title, company_domain, ...}."""
    if not isinstance(rec, dict):
        return {}
    org = rec.get("organization") if isinstance(rec.get("organization"), dict) else {}
    dom = _s(org, "primary_domain", "domain") or ""
    if not dom:
        for job in rec.get("employment_history") or []:
            if isinstance(job, dict) and job.get("current"):
                dom = _s(job, "organization_domain") or dom
    loc = ", ".join(x for x in [_s(rec, "city"), _s(rec, "state"), _s(rec, "country")] if x) or None
    phone = None
    for n in rec.get("phone_numbers") or []:
        if isinstance(n, dict):
            raw = _s(n, "sanitized_number", "raw_number")
            if raw:
                phone = raw
                break
    if not phone:
        phone = _s(rec, "sanitized_phone", "phone")
    return {
        "first_name": _s(rec, "first_name") or "",
        "last_name": _s(rec, "last_name") or "",
        "email": _s(rec, "email"),
        "email_status": _s(rec, "email_status"),
        "phone": phone,
        "linkedin_url": _s(rec, "linkedin_url"),
        "title": _s(rec, "title"),
        "headline": _s(rec, "headline"),
        "location": loc,
        "company_name": _s(org, "name"),
        "company_domain": membership.registrable(dom) if dom else "",
    }


def map_org(body: dict) -> dict:
    """organizations/enrich body → {name, domain, linkedin_url}."""
    o = body.get("organization") if isinstance(body, dict) else None
    if not isinstance(o, dict):
        return {"name": None, "domain": "", "linkedin_url": ""}
    return {
        "name": _s(o, "name"),
        "domain": membership.registrable(_s(o, "primary_domain", "domain")),
        "linkedin_url": _s(o, "linkedin_url") or "",
    }


# --- thin async clients -----------------------------------------------------
async def _post(token: str, url: str, *, params=None, body=None, timeout: float) -> dict:
    headers = {"X-Api-Key": token, "Content-Type": "application/json", "Cache-Control": "no-cache"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, headers=headers, params=params or {}, json=body or {})
    except httpx.HTTPError as e:
        raise ApolloNativeError(f"could not reach Apollo: {e}") from e
    if r.status_code >= 400:
        raise ApolloNativeError(f"apollo {url.rsplit('/', 1)[-1]} -> {r.status_code}: {r.text[:300]}")
    try:
        out = r.json()
    except ValueError as e:
        raise ApolloNativeError("apollo returned a non-JSON body") from e
    if not isinstance(out, dict):
        raise ApolloNativeError("apollo returned a non-object body")
    return out


async def org_enrich(token: str, domain: str, *, timeout: float = 30.0) -> dict:
    d = membership.registrable(domain)
    if not d:
        return {"name": None, "domain": "", "linkedin_url": ""}
    headers = {"X-Api-Key": token, "Content-Type": "application/json", "Cache-Control": "no-cache"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(ORG_ENRICH_URL, headers=headers, params={"domain": d})
    except httpx.HTTPError as e:
        raise ApolloNativeError(f"could not reach Apollo: {e}") from e
    if r.status_code >= 400:
        raise ApolloNativeError(f"apollo org_enrich -> {r.status_code}: {r.text[:200]}")
    try:
        return map_org(r.json())
    except ValueError as e:
        raise ApolloNativeError("apollo org_enrich non-JSON body") from e


async def people_search(
    token: str, domain: str | None, titles: list[str], country: str | None,
    per_page: int, *, timeout: float = 120.0,
) -> list[dict]:
    """FREE discovery → raw-lead dicts (mapped via map_search)."""
    out = await _post(token, SEARCH_URL, body=search_input(domain, titles, country, per_page),
                      timeout=timeout)
    people = out.get("people") or []
    return [map_search(p) for p in people if isinstance(p, dict)]


async def bulk_match(token: str, hints: list[dict], *, timeout: float = 60.0) -> list[dict]:
    """Enrich up to 10 hints/call. Each hint: {id} | {first_name,last_name,domain}
    | {linkedin_url} | {email}. Returns a list ALIGNED 1:1 with `hints` — each
    element is a mapped match dict (work email, no personal) or `{}` for a miss,
    so callers can zip results straight back to their leads. Hints must be
    non-empty dicts (the caller builds them per-lead)."""
    aligned: list[dict] = []
    for i in range(0, len(hints), 10):
        chunk = hints[i:i + 10]
        out = await _post(
            token, BULK_MATCH_URL,
            params={"reveal_personal_emails": "false"}, body={"details": chunk},
            timeout=timeout,
        )
        matches = out.get("matches") or []
        for j in range(len(chunk)):
            m = matches[j] if j < len(matches) else None
            aligned.append(map_match(m) if isinstance(m, dict) else {})
    return aligned
