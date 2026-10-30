"""Deterministic discovery helpers — query generation, candidate extraction.

Two lanes per mPower category:
  * OEM lane     — drone MANUFACTURERS who would BUY mPower's packs.
  * Channel lane — resellers / distributors of drone batteries.

Claude PROPOSES extra query terms (non-load-bearing); Apify executes; this
module's deterministic code turns raw SERP rows into candidate company domains,
attributes each to the (category, ctype) of the lane that surfaced it, and owns
the fallback query set. A blocklist drops directory / marketplace / social /
research-firm / news domains so a stored candidate is always a company's OWN
site. The Claude classifier then decides if it is a genuine customer.
"""

from __future__ import annotations

from app.customers.service import normalize_domain
from app.segments import segment_phrase

# Domains that are never a customer's own site (directories, marketplaces, social,
# video, reference, market-research firms, search). Dropped — deterministic
# lowercased substring match on the host.
BLOCKLIST = {
    "alibaba.com", "made-in-china.com", "indiamart.com", "tradeindia.com",
    "exporthub.com", "globalsources.com", "dhgate.com", "aliexpress.com",
    "amazon.", "ebay.", "flipkart.com", "etsy.com",
    "reddit.com", "youtube.com", "youtu.be", "facebook.com", "instagram.com",
    "linkedin.com", "twitter.com", "x.com", "quora.com", "pinterest.com",
    "wikipedia.org", "google.", "bing.com", "medium.com", "blogspot.",
    "marketsandmarkets.com", "polarismarketresearch.com", "grandviewresearch.com",
    "mordorintelligence.com", "fortunebusinessinsights.com", "statista.com",
    "volza.com", "importyeti.com", "eximpedia.app", "seair.co.in", "thetradevision.com",
    "unmannedsystemstechnology.com", "dronelife.com", "suasnews.com",
}


def oem_term(category: str) -> str | None:
    """OEM-lane query for a category — drone MAKERS who would buy this pack.

    The catalog stores bare labels ("Mapping") that drift off-domain searched raw.
    `segment_phrase` anchors to the drone segment (stripping "battery" so the lane
    targets drone makers, not battery makers). Returns None for a non-segment
    category so it issues no query."""
    seg = segment_phrase(category)
    return f"{seg} manufacturer company" if seg else None


def channel_term(category: str) -> str | None:
    """Channel-lane query — resellers/distributors of this drone battery. Drone-
    anchored via `segment_phrase`; None for a non-segment category."""
    seg = segment_phrase(category)
    return f"{seg} battery distributor reseller supplier" if seg else None


def category_query_map(categories: list[str]) -> dict[str, dict]:
    """{ per-lane search query -> {"category":<mPower cat>, "ctype":<provisional>} }.

    Lets discovery attribute each found company to the CATEGORY + provisional TYPE
    of the lane that surfaced it. OEM-lane → ctype "OEM"; channel-lane → ctype None
    (Reseller vs Distributor decided later from evidence). First lane wins a shared
    query (deterministic). Non-segment categories are skipped (no query)."""
    out: dict[str, dict] = {}
    for c in categories:
        oq = oem_term(c)
        cq = channel_term(c)
        if oq:
            out.setdefault(oq, {"category": c, "ctype": "OEM"})
        if cq:
            out.setdefault(cq, {"category": c, "ctype": None})
    return out


def seed_queries(categories: list[str], round_idx: int) -> list[str]:
    """Deterministic fallback query set for a round (used if Claude proposes none).

    Round 0 = per-category (drone-anchored) OEM + channel lanes + global/India
    staples. Later rounds add region / synonym / channel angles so coverage widens
    toward plateau.
    """
    if round_idx == 0:
        qs = [
            # OEM staples (drone makers who BUY packs)
            "drone UAV manufacturer company list",
            "agriculture spraying drone manufacturer",
            "surveillance survey mapping drone manufacturer",
            # channel staples (resellers / distributors of drone batteries)
            "drone battery distributor reseller supplier",
            "drone battery authorized distributor dealer",
            # India staples (Local sub-tab coverage from round 0)
            "drone manufacturer India company",
            "drone battery distributor India",
        ]
        for c in categories:
            oq = oem_term(c)
            cq = channel_term(c)
            if oq:
                qs.append(oq)
            if cq:
                qs.append(cq)
        return qs
    angles = [
        ["agriculture drone manufacturer India", "VTOL drone manufacturer company",
         "drone battery distributor Europe", "UAV maker company China"],
        ["delivery drone manufacturer", "mapping survey drone manufacturer company",
         "drone battery wholesale distributor", "drone spare parts distributor company"],
        ["industrial drone OEM manufacturer", "defence surveillance drone maker",
         "drone battery reseller online store company", "UAV battery distributor supplier"],
        ["long endurance drone manufacturer", "agritech spraying drone company",
         "drone accessories distributor wholesaler", "drone battery dealer network company"],
    ]
    return angles[(round_idx - 1) % len(angles)]


def marketplace_resolve_query(name: str) -> list[str]:
    """Name→domain resolve query for a marketplace row (IndiaMART) that has no
    own-domain. The existing google-search lane + blocklist turns the first organic
    company result into a canonical domain."""
    n = (name or "").strip()
    if not n:
        return []
    return [f'"{n}" official website drone battery']


def extract_candidates(
    results: list[dict], meta_by_query: dict[str, dict] | None = None
) -> list[dict]:
    """Raw SERP rows → de-duped candidate company domains (blocklist applied).

    Returns dicts: name, website, domain, category, ctype, source_url, snippet.
    Deterministic: first occurrence of a domain wins; ordering preserved. When
    `meta_by_query` is given, each candidate is tagged with the (category, ctype)
    of the lane whose search surfaced it; a domain first seen via a non-lane query
    gets category/ctype None (the classifier fills them later)."""
    meta_by_query = meta_by_query or {}
    seen: set[str] = set()
    out: list[dict] = []
    for r in results:
        url = r.get("url") or ""
        dom = normalize_domain(url)
        if not dom or dom in seen:
            continue
        if any(b in dom for b in BLOCKLIST):
            continue
        seen.add(dom)
        meta = meta_by_query.get(r.get("query") or "") or {}
        out.append({
            "name": name_from_domain(dom),
            "website": f"https://{dom}/",
            "domain": dom,
            "category": meta.get("category"),
            "ctype": meta.get("ctype"),
            "source_url": url,
            "snippet": (r.get("description") or "")[:400],
        })
    return out


_DOMAIN_NOISE = {"com", "net", "org", "co", "in", "io", "cn", "uk", "de", "us", "biz", "info"}


def name_from_domain(dom: str) -> str:
    """e.g. 'garudaaerospace.com' -> 'Garudaaerospace'; 'ideaforge.in' -> 'Ideaforge'."""
    if not dom:
        return "(unknown)"
    label = dom.split(".")[0]
    words = [w for w in label.replace("-", " ").replace("_", " ").split() if w not in _DOMAIN_NOISE]
    if not words:
        words = [label]
    return " ".join(w.capitalize() for w in words)[:120]


def profile_queries(name: str, domain: str) -> list[str]:
    """The line-by-line Apify enrichment pass — a multi-angle search for ONE company,
    run in a single google-search actor call. High recall on the fields the
    classifier fills: identity, HQ country, and whether the company BUILDS drones
    (OEM) or RESELLS/DISTRIBUTES batteries (channel). Search snippets bypass JS/cookie
    walls that defeat a raw homepage crawl, so the classifier is never starved."""
    n = (name or "").strip()
    dom = (domain or "").strip()
    qn = f'"{n}"' if n else dom
    qs = [
        f"{dom} drone company about",                                    # identity from the site
        f"{qn} drone UAV manufacturer OR maker products",                # is-it-an-OEM (builds drones)
        f"{qn} company headquarters country location",                   # HQ country
        f"{qn} drone battery distributor OR reseller OR dealer",         # is-it-a-channel
        f"{qn} agriculture surveillance survey delivery drone",          # segment / category signal
    ]
    return [q for q in qs if q.strip()]


def evidence_text(pages: list[dict], search_results: list[dict]) -> str:
    """Assemble the evidence blob the classifier reads — search snippets FIRST
    (they survive cookie/JS walls), then the company's own crawled pages. Bounded
    length so the prompt stays cheap + focused."""
    parts: list[str] = []
    for r in search_results[:36]:
        line = f"{r.get('title','')} — {r.get('description','')}".strip(" —")
        if line:
            parts.append("[search] " + line)
    for pg in pages[:4]:
        md = (pg.get("markdown") or "")[:1200]
        if md:
            parts.append(f"[site:{pg.get('url','')}] {md}")
    return "\n\n".join(parts)[:5500] or "(no evidence gathered)"
