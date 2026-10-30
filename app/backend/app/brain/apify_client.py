"""Thin Apify website-crawl client for the Brain sync (module-local, OP #11).

Own copy rather than importing app.scraping (feature→feature is disallowed).
Uses Apify's run-sync-get-dataset-items endpoint. Apify slugs use '~' in the API
path (owner~name).
"""

from __future__ import annotations

import httpx

CRAWL_ACTOR = "apify~website-content-crawler"
_BASE = "https://api.apify.com/v2/acts"


class ApifyError(RuntimeError):
    """Raised when the Apify crawl fails (auth, actor, or transport)."""


def crawl_input(start_url: str, *, max_pages: int = 40) -> dict:
    """The exact Apify actor input — single source of truth (also shown read-only
    in the dev-reference panel, so the displayed query never drifts from the run)."""
    return {
        "startUrls": [{"url": start_url}],
        "maxCrawlPages": max_pages,
        "crawlerType": "cheerio",
        "saveMarkdown": True,
        "maxCrawlDepth": 3,
    }


async def crawl_site(
    token: str,
    start_url: str,
    *,
    max_pages: int = 40,
    timeout: float = 300.0,
) -> list[dict]:
    """Crawl one site (same-domain, bounded, cheap cheerio) -> cleaned page records."""
    actor_input = crawl_input(start_url, max_pages=max_pages)
    url = f"{_BASE}/{CRAWL_ACTOR}/run-sync-get-dataset-items"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, params={"token": token}, json=actor_input)
    except httpx.HTTPError as e:
        raise ApifyError(f"could not reach Apify: {e}") from e
    if resp.status_code >= 400:
        raise ApifyError(f"Apify returned {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
    except ValueError as e:
        raise ApifyError("Apify returned a non-JSON body") from e
    if not isinstance(data, list):
        raise ApifyError("Apify returned an unexpected (non-list) dataset")
    return [_clean(it) for it in data]


def _clean(item: dict) -> dict:
    md = item.get("markdown") or item.get("text") or ""
    meta = item.get("metadata") or {}
    return {
        "url": item.get("url") or meta.get("canonicalUrl") or "",
        "title": meta.get("title") or item.get("title") or "",
        "markdown": md.strip(),
    }
