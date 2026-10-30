"""Multi-source discovery LANE ADAPTERS (S-MS1) — input-builders + output-mappers.

PURE module (no Apify/DB calls) so it is unit-testable offline; the orchestration
(`discover_lane`) lives in `apify_client.py`. Each Apify actor is a LANE:
`build_input(queries, region, max_items)` produces the actor's exact input;
`map_items(items)` normalizes raw dataset rows into the SAME candidate dict the
existing discovery emits (`sourcing.extract_candidates`) PLUS phone/email/source.

Field names are verbatim from the actor docs under
`directives/06062026_scrape_gen2/apify_docs/`, VERIFIED against a live smoke run
(`directives/07062026_multisource_discovery/smoke/RESULTS.md`) — KI-28 rule:
reality over the doc. Every mapper is defensive: a missing/odd-typed key degrades
to None, never KeyError.

Lane set = the 6 smoke-proven actors (Kompass + Made-in-China DROPPED — KI-29/30).
The existing Google-search lane stays in `sync.py`; these run ALONGSIDE it.
"""

from __future__ import annotations

from app.customers.service import normalize_domain

# slug = Apify '~' API form. marketplace=True → no own-domain in output (Stage-2
# resolves it). proxy=True → residential proxy required. multi=True → one call
# takes the whole query array; else one call per query.
LANES: dict[str, dict] = {
    "maps":      {"slug": "compass~crawler-google-places",            "multi": True,  "marketplace": False, "proxy": False},
    "linkedin":  {"slug": "harvestapi~linkedin-company-search",       "multi": False, "marketplace": False, "proxy": False},
    "indiamart": {"slug": "thirdwatch~indiamart-supplier-scraper",    "multi": True,  "marketplace": True,  "proxy": False},
    "thomasnet": {"slug": "parseforge~thomasnet-scraper",             "multi": False, "marketplace": False, "proxy": True},
    "europages": {"slug": "santamaria-automations~europages-scraper", "multi": False, "marketplace": False, "proxy": False},
    "wlw":       {"slug": "santamaria-automations~wlw-de-scraper",    "multi": False, "marketplace": False, "proxy": False},
}

_RESIDENTIAL = {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}


def _first(d: dict, *keys: str):
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def _phone_str(v):
    """Phone may be a string OR a {number,extension} dict (LinkedIn — the doc
    sample wrongly showed null; live smoke returns a dict). Reduce to a string."""
    if isinstance(v, dict):
        v = v.get("number") or v.get("phone") or v.get("formatted")
    return str(v).strip() if v else None


def _ensure_scheme(v):
    """Normalize a website to an absolute URL. Some lanes (LinkedIn) return a BARE
    domain ('www.zxaero.com') or a schemeless value — stored raw it crashes the
    stage-2 httpx resolve ('unknown url type'). Prefix https:// so the stored website
    is always a valid, clickable absolute URL."""
    u = str(v).strip() if v else ""
    if not u:
        return None
    if "://" not in u:
        u = "https://" + u.lstrip("/")
    return u


def _cand(*, name, source: str, website=None, country=None, phone=None,
          email=None, source_url=None, snippet="") -> dict:
    """A candidate in the SAME shape `sourcing.extract_candidates` emits, plus
    phone/email/discovery_source. category + ctype are left None (the classifier
    fills them). domain is derived from website (None for marketplace lanes)."""
    website = _ensure_scheme(website)
    return {
        "name": (str(name).strip() if name else None),
        "website": website,
        "domain": normalize_domain(website) if website else None,
        "category": None,
        "ctype": None,
        "country": (str(country).strip() if country else None),
        "phone": _phone_str(phone),
        "email": (str(email).strip() if email and "@" in str(email) else None),
        "source_url": source_url or website,
        "snippet": (str(snippet)[:400] if snippet else ""),
        "discovery_source": source,
    }


# ============================ INPUT BUILDERS =================================

def build_input(lane: str, queries: list[str], region: str | None, max_items: int) -> dict:
    qs = [q for q in (queries or []) if q and q.strip()]
    q1 = qs[0] if qs else ""
    cfg = LANES[lane]
    proxy = {"proxyConfiguration": dict(_RESIDENTIAL)} if cfg["proxy"] else {}

    if lane == "maps":
        inp = {"searchStringsArray": qs, "maxCrawledPlacesPerSearch": max_items,
               "language": "en", "skipClosedPlaces": True}
        if region:
            inp["locationQuery"] = region
        return inp
    if lane == "linkedin":
        inp = {"searchQuery": q1[:300], "maxItems": max_items}
        if region:
            inp["locations"] = [region]
        return inp
    if lane == "indiamart":
        return {"queries": qs, "location": (region or ""), "category": "all",
                "maxResultsPerQuery": min(max_items, 200)}
    if lane == "thomasnet":
        return {"query": q1, "searchMode": "all", "companyType": "any",
                "area": (region or "NA"), "maxItems": max_items, **proxy}
    if lane == "europages":
        return {"searchQuery": q1, "searchType": "company",
                "country": (region or "DE"), "maxResults": max_items,
                "includeDetails": True}
    if lane == "wlw":
        return {"keyword": q1, "country": (region or "DE"),
                "maxResults": max_items, "includeDetails": True}
    raise KeyError(f"unknown lane {lane!r}")


# ============================ OUTPUT MAPPERS ================================

def _map_maps(items):
    return [_cand(
        name=_first(it, "title", "name"), source="maps",
        website=_first(it, "website", "url"),
        country=_first(it, "countryCode", "country"),
        phone=_first(it, "phone", "phoneUnformatted"),
        source_url=_first(it, "url", "website"),
        snippet=_first(it, "categoryName", "description") or "",
    ) for it in items]


def _map_linkedin(items):
    out = []
    for it in items:
        locs = it.get("locations")
        loc0 = locs[0] if isinstance(locs, list) and locs and isinstance(locs[0], dict) else {}
        parsed = loc0.get("parsed") if isinstance(loc0.get("parsed"), dict) else {}
        out.append(_cand(
            name=it.get("name"), source="linkedin", website=it.get("website"),
            country=_first(parsed, "country") or _first(loc0, "country"),
            phone=it.get("phone"),
            source_url=_first(it, "linkedinUrl", "website"),
            snippet=_first(it, "description", "tagline") or "",
        ))
    return out


def _map_indiamart(items):  # marketplace — no own-domain
    return [_cand(
        name=it.get("company_name"), source="indiamart", website=None, country="India",
        phone=it.get("phone"), source_url=_first(it, "catalog_url", "product_url"),
        snippet=_first(it, "product_name") or "",
    ) for it in items]


def _map_thomasnet(items):
    out = []
    for it in items:
        addr = it.get("address") if isinstance(it.get("address"), dict) else {}
        out.append(_cand(
            name=it.get("name"), source="thomasnet", website=it.get("website"),
            country="United States",  # ThomasNet = NA directory; no country field
            phone=_first(it, "primaryPhone", "phone"),
            source_url=_first(it, "sourceUrl", "website"),
            snippet=" ".join(str(x) for x in (it.get("type"), addr.get("city"), addr.get("state")) if x),
        ))
    return out


def _map_santamaria(source):
    """Europages + wlw share the santamaria schema."""
    def _m(items):
        return [_cand(
            name=it.get("name"), source=source, website=it.get("website"),
            country=_first(it, "country", "country_code"),
            phone=it.get("phone"), email=it.get("email"),
            source_url=_first(it, "source_url", "detail_url", "website"),
            snippet=_first(it, "supplier_type", "description") or "",
        ) for it in items]
    return _m


MAPPERS = {
    "maps": _map_maps,
    "linkedin": _map_linkedin,
    "indiamart": _map_indiamart,
    "thomasnet": _map_thomasnet,
    "europages": _map_santamaria("europages"),
    "wlw": _map_santamaria("wlw"),
}


def map_items(lane: str, items: list[dict]) -> list[dict]:
    return MAPPERS[lane]([it for it in (items or []) if isinstance(it, dict)])


# Ordered list of own-domain lanes (merged before the marketplace lanes so an
# own-domain phone/email wins a shared company — see discovery._merge_one / RP3).
OWN_DOMAIN_LANES = ("maps", "linkedin", "thomasnet", "europages", "wlw")
MARKETPLACE_LANES = ("indiamart",)
