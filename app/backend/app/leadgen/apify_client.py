"""Thin async Apify client for Generate-Leads (module-local, OP #11).

Two surfaces, both via Apify's run-sync-get-dataset-items endpoint (no run-id
polling):
  * `run_linkedin_search`  — the LINKEDIN_ACTOR people search (primary).
  * `run_fallback_search`  — an Apollo-sourced finder actor (fallback / merge).

Own copy rather than importing app.scraping / app.customers (feature→feature is
disallowed). Apify slugs use '~' in the API path (owner~name). A passed-in
CallCounter is incremented per actor run so the staged job honors the runaway
backstop. Defensive: non-2xx / non-list / invalid JSON → ApifyError.
"""

from __future__ import annotations

import httpx

from app.leadgen import config, sourcing

_BASE = "https://api.apify.com/v2/acts"


class ApifyError(RuntimeError):
    """Raised when an Apify run fails (auth, actor, or transport)."""


class CallCounter:
    """Deterministic actor-call accounting — the runaway-loop backstop owner."""

    def __init__(self, max_calls: int = config.MAX_ACTOR_CALLS) -> None:
        self.max_calls = max_calls
        self.calls = 0

    def check(self) -> None:
        if self.calls >= self.max_calls:
            raise ApifyError(
                f"runaway-loop backstop: {self.calls} actor calls "
                f">= MAX_ACTOR_CALLS={self.max_calls}"
            )

    def record(self) -> None:
        self.calls += 1


async def _run(
    token: str, actor: str, actor_input: dict, counter: CallCounter, timeout: float
) -> list[dict]:
    counter.check()
    url = f"{_BASE}/{actor}/run-sync-get-dataset-items"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, params={"token": token}, json=actor_input)
    except httpx.HTTPError as e:
        counter.record()
        raise ApifyError(f"could not reach Apify: {e}") from e
    counter.record()
    if resp.status_code >= 400:
        raise ApifyError(f"Apify {actor} returned {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
    except ValueError as e:
        raise ApifyError("Apify returned a non-JSON body") from e
    if not isinstance(data, list):
        raise ApifyError("Apify returned an unexpected (non-list) dataset")
    return data


async def run_company_search(
    token: str,
    queries: list[str],
    counter: CallCounter,
    *,
    results: int | None = None,
    country_code: str = "",
    timeout: float = 120.0,
) -> list[dict]:
    """Stage-0 SERP scrape → flattened organic results ({query,title,url,description})."""
    if not queries:
        return []
    items = await _run(
        token, config.SEARCH_ACTOR,
        sourcing.build_search_input(queries, results=results, country_code=country_code),
        counter, timeout,
    )
    out: list[dict] = []
    for page in items:
        q = (page.get("searchQuery", {}) or {}).get("term", "")
        for r in page.get("organicResults", []) or []:
            out.append({
                "query": q,
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
            })
    return out


async def run_apollo_search(
    token: str,
    company_name: str,
    anchor_domain: str | None,
    titles: list[str],
    country: str | None,
    counter: CallCounter,
    *,
    results: int | None = None,
    timeout: float = 180.0,
) -> list[dict]:
    """Engine 1 (PRIMARY): Apollo finder by company_domain + titles."""
    actor_input = sourcing.build_apollo_input(
        company_name, anchor_domain, titles, country, results=results
    )
    return await _run(token, config.APOLLO_ACTOR, actor_input, counter, timeout)


async def run_company_employees(
    token: str,
    company_or_url: str,
    titles: list[str],
    counter: CallCounter,
    *,
    results: int | None = None,
    timeout: float = 180.0,
) -> list[dict]:
    """Engine 2: LinkedIn company-employees (by company URL/name)."""
    if not company_or_url:
        return []
    actor_input = sourcing.build_company_employees_input(company_or_url, titles, results=results)
    return await _run(token, config.COMPANY_EMPLOYEES_ACTOR, actor_input, counter, timeout)


async def run_email_finder(
    token: str,
    domain: str,
    category: str,
    counter: CallCounter,
    *,
    max_leads: int | None = None,
    timeout: float = 180.0,
) -> list[dict]:
    """Engine 4 (NEW): snipercoder decision-maker email-finder for one domain +
    decision-maker category. Returns `NN_`-prefixed records (email + phone)."""
    if not domain:
        return []
    n = int(max_leads if max_leads is not None else config.EMAIL_FINDER_PER_CATEGORY)
    actor_input = sourcing.build_email_finder_input(domain, category, n)
    return await _run(token, config.EMAIL_FINDER_ACTOR, actor_input, counter, timeout)


async def run_linkedin_search(
    token: str,
    company_name: str,
    titles: list[str],
    country: str | None,
    counter: CallCounter,
    *,
    li_url: str | None = None,
    results: int | None = None,
    timeout: float = 180.0,
) -> list[dict]:
    """Engine 3 (revived): LinkedIn profile-search anchored on the company
    LinkedIn URL (`li_url`) when known, else a fuzzy company-name search."""
    actor_input = sourcing.build_linkedin_input(
        company_name, titles, country, li_url=li_url, results=results
    )
    return await _run(token, config.LINKEDIN_ACTOR, actor_input, counter, timeout)


async def run_fallback_search(
    token: str,
    actor_id: str,
    company_name: str,
    titles: list[str],
    country: str | None,
    counter: CallCounter,
    *,
    anchor_domain: str | None = None,
    results: int | None = None,
    timeout: float = 180.0,
) -> list[dict]:
    """Back-compat: an Apollo-sourced finder for the company (now domain-aware)."""
    actor_input = sourcing.build_apollo_input(
        company_name, anchor_domain, titles, country, results=results
    )
    return await _run(token, actor_id, actor_input, counter, timeout)
