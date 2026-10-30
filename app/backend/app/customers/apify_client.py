"""Thin Apify client for customer discovery (module-local, OP #11).

Two surfaces, both via Apify's run-sync-get-dataset-items endpoint:
  * `run_search`  — google-search-scraper → organic results (discovery + enrich).
  * `crawl_site`  — website-content-crawler → a company's own pages (type signal).

Own copy rather than importing app.competitors / app.scraping (feature→feature is
disallowed). Apify slugs use '~' in the API path (owner~name). `calls` on a passed-in
counter is incremented per actor run so the sync job honors the runaway backstop.
"""

from __future__ import annotations

import httpx

from app.customers import config

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


def search_input(queries: list[str], *, results_per_query: int, country_code: str = "") -> dict:
    """The exact google-search-scraper input (also shown read-only in dev-info)."""
    inp: dict = {
        "queries": "\n".join(queries),
        "resultsPerPage": results_per_query,
        "maxPagesPerQuery": 1,
        "saveHtml": False,
        "mobileResults": False,
    }
    if country_code:
        inp["countryCode"] = country_code
    return inp


def crawl_input(start_url: str, *, max_pages: int = 4) -> dict:
    return {
        "startUrls": [{"url": start_url}],
        "maxCrawlPages": max_pages,
        "crawlerType": "cheerio",
        "saveMarkdown": True,
        "maxCrawlDepth": 2,
    }


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


async def run_search(
    token: str,
    queries: list[str],
    counter: CallCounter,
    *,
    results_per_query: int = config.RESULTS_PER_QUERY,
    country_code: str = "",
    timeout: float = 180.0,
) -> list[dict]:
    """Run google-search queries → flattened organic results (query/title/url/desc)."""
    if not queries:
        return []
    items = await _run(
        token,
        config.SEARCH_ACTOR,
        search_input(queries, results_per_query=results_per_query, country_code=country_code),
        counter,
        timeout,
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


async def crawl_site(
    token: str,
    start_url: str,
    counter: CallCounter,
    *,
    max_pages: int = config.CRAWL_PAGES_PER_CUSTOMER,
    timeout: float = 180.0,
) -> list[dict]:
    """Crawl one company's site → cleaned page records (url/title/markdown)."""
    data = await _run(
        token, config.CRAWL_ACTOR, crawl_input(start_url, max_pages=max_pages), counter, timeout
    )
    return [_clean(it) for it in data]


def _clean(item: dict) -> dict:
    md = item.get("markdown") or item.get("text") or ""
    meta = item.get("metadata") or {}
    return {
        "url": item.get("url") or meta.get("canonicalUrl") or "",
        "title": meta.get("title") or item.get("title") or "",
        "markdown": md.strip(),
    }


# --- S-MS1 multi-source lanes -----------------------------------------------
async def run_actor(
    token: str, slug: str, actor_input: dict, counter: CallCounter, *, timeout: float = 180.0
) -> list[dict]:
    """Generic Apify run-sync-get-dataset-items for ANY actor slug (the multi-source
    lanes). Returns the raw dataset list; the caller's lane mapper normalizes it."""
    return await _run(token, slug, actor_input, counter, timeout)


async def discover_lane(
    token: str, lane: str, queries: list[str], region: str | None, counter: CallCounter,
    *, max_items: int, timeout: float = 180.0,
) -> list[dict]:
    """Run ONE multi-source lane → normalized candidate dicts (via lanes.map_items).

    Multi-query-capable lanes (Maps/IndiaMART) take the whole array in one call; the
    rest issue one actor call per query. A single failing query degrades to [] so one
    bad query never sinks the lane. The runaway backstop (counter) still applies."""
    from app.customers import lanes  # lazy: lanes is pure, avoids import-time coupling

    cfg = lanes.LANES[lane]
    raw: list[dict] = []
    if cfg["multi"]:
        try:
            raw = await run_actor(
                token, cfg["slug"], lanes.build_input(lane, queries, region, max_items),
                counter, timeout=timeout,
            )
        except ApifyError:
            raw = []
    else:
        for q in queries:
            try:
                items = await run_actor(
                    token, cfg["slug"], lanes.build_input(lane, [q], region, max_items),
                    counter, timeout=timeout,
                )
            except ApifyError:
                items = []
            raw.extend(items)
    return lanes.map_items(lane, raw)
