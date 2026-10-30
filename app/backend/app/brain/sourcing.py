"""Catalog data sourcing — Shopify products.json (structured) + services (crawl).

Apify-first applies to crawling/search; the Shopify `products.json` is a clean
public STRUCTURED endpoint, so a direct GET is the right tool. All prices kept
as exact decimal strings (never float); category from Shopify tags.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx

MPOWER_HOME = "https://mpowerlithium.com/"
PRODUCTS_URL = "https://mpowerlithium.com/products.json?limit=250"

# Known service pages (slug -> name, service type). Auditable + stable.
SERVICE_PAGES = {
    "custom-drone-batteries": ("Custom Drone Battery Pack design", "Custom packs"),
    "type-certificate": ("Type Certification (Form D-1) assistance", "Certification"),
    "drone-battery-recycling": ("Lithium-Ion Drone Battery Recycling", "Recycling"),
    "dealership": ("Dealership / Partner program", "Channel"),
    "corporate-orders": ("Corporate / Bulk Orders", "B2B sales"),
    "get-a-quote": ("Customized Bulk-Order Quote", "B2B sales"),
    "research-and-development": ("Battery R&D", "R&D"),
    "batteries-for-robotics-applications": ("Batteries for Robotics Applications", "Adjacent market"),
}


def _price_str(variants: list[dict]) -> str | None:
    if not variants:
        return None
    raw = variants[0].get("price")
    if raw in (None, ""):
        return None
    try:
        return str(Decimal(str(raw)))
    except (InvalidOperation, ValueError):
        return None


async def fetch_products(url: str = PRODUCTS_URL) -> list[dict]:
    """GET the Shopify catalog -> normalized product rows for service.upsert_synced."""
    async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
        r = await client.get(url)
    r.raise_for_status()
    prods = r.json().get("products", [])
    rows = []
    for p in prods:
        tags = p.get("tags") or []
        handle = p.get("handle") or ""
        rows.append({
            "kind": "product",
            "name": p.get("title") or handle,
            "handle": handle,
            "category": tags[0] if tags else "Uncategorized",
            "price_inr": _price_str(p.get("variants") or []),
            "source_url": f"https://mpowerlithium.com/products/{handle}",
        })
    return rows


def services_from_crawl(pages: list[dict]) -> list[dict]:
    """Derive service rows from crawl pages, keyed by known service slugs."""
    by_slug = {}
    for pg in pages:
        slug = (pg.get("url", "") or "").rstrip("/").rsplit("/", 1)[-1]
        by_slug[slug] = pg
    rows = []
    for slug, (name, stype) in SERVICE_PAGES.items():
        pg = by_slug.get(slug)
        rows.append({
            "kind": "service",
            "name": name,
            "handle": slug,
            "category": stype,
            "price_inr": None,
            "source_url": pg.get("url") if pg else f"https://mpowerlithium.com/pages/{slug}",
        })
    return rows


def evidence_for(row_name: str, row_handle: str | None, pages: list[dict]) -> str:
    """Best-effort crawl snippet that corroborates a catalog row (≤500 chars)."""
    if row_handle:
        for pg in pages:
            if row_handle and row_handle in (pg.get("url", "") or ""):
                return (pg.get("markdown") or "")[:500]
    token = (row_name or "")[:24].lower()
    if token:
        for pg in pages:
            if token in (pg.get("markdown") or "").lower():
                return (pg.get("markdown") or "")[:500]
    return ""
