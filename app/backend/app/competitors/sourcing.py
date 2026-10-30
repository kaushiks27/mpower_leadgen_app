"""Deterministic discovery helpers — query generation, candidate extraction.

Claude PROPOSES query terms (non-load-bearing); Apify executes; this module's
deterministic code turns raw SERP rows into candidate competitor domains and
owns the fallback query set. Queries are generated PER mPower product/service
category (so competitors are found + analysed against mPower's own categories).

A blocklist drops directory / marketplace / social / research-firm / news
domains so a stored candidate is always a company's OWN site — never a listing
page. The Claude classifier then decides if that company is a true competitor.
"""

from __future__ import annotations

from app.competitors.service import normalize_domain
from app.segments import segment_phrase

# Domains that are never a competitor's own site (directories, marketplaces,
# social, video, reference, market-research firms, search). Candidates on these
# hosts are dropped — deterministic, lowercased substring match on the host.
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


def _category_term(category: str) -> str | None:
    """The PRIMARY drone-anchored competitor query for an mPower category.

    The catalog stores bare labels ("Mapping", "Surveillance") that drift off-domain
    if searched raw ("Mapping manufacturer" -> Google Maps). `segment_phrase` anchors
    them to the drone segment; we append the battery-MAKER tail. Returns None for a
    non-segment / operational category (e.g. "Recycling") so it issues no query.
    NB: a COMPETITOR is a battery/pack MAKER — never a drone OEM (that is a buyer →
    a customer). The 'battery pack manufacturer' tail keeps the search seller-side."""
    seg = segment_phrase(category)
    return f"{seg} battery pack manufacturer" if seg else None


def category_competitor_queries(category: str) -> list[str]:
    """SPECIFIC, multi-angle competitor queries for ONE mPower category (critical-1).

    Generic queries surface drone OEMs + listicles; these target battery-pack MAKERS
    for the exact drone segment (manufacturer / supplier / OEM angles) so both the
    quality AND the quantity of true competitors are high. The PRIMARY query (used for
    category attribution) leads the list. Returns [] for a non-segment category."""
    seg = segment_phrase(category)
    if not seg:
        return []
    return [
        f"{seg} battery pack manufacturer",                 # PRIMARY (attribution key)
        f"{seg} battery pack supplier company",
        f"{seg} lithium battery pack OEM manufacturer",
    ]


def category_query_map(categories: list[str]) -> dict[str, str]:
    """{ per-category competitor query -> the originating mPower category }.

    Lets discovery attribute each found company to the CATEGORY whose search
    surfaced it (category-first pipeline: the originating search is the source of
    truth for the Category column; Claude only fills the gaps it leaves). Keyed by
    EVERY competitor-query angle we issue for the category (the primary + sharper
    angles). Non-segment categories are skipped (no query)."""
    out: dict[str, str] = {}
    for c in categories:
        for q in category_competitor_queries(c):
            out.setdefault(q, c)  # first category wins a shared query (deterministic)
    return out


def seed_queries(categories: list[str], round_idx: int) -> list[str]:
    """Deterministic fallback query set for a round (used if Claude proposes none).

    Round 0 = per-category (drone-anchored) + the staple discovery queries. Later
    rounds add synonym / region / channel angles so coverage keeps widening toward
    plateau.
    """
    if round_idx == 0:
        qs = [
            # global staples
            "drone battery pack manufacturer",
            "top drone battery manufacturers list",
            "UAV lithium battery pack supplier",
            "custom drone battery pack manufacturer",
            # India staples (Local sub-tab coverage from round 0)
            "drone battery manufacturer India",
            "agriculture drone battery manufacturer India",
            "lithium drone battery pack manufacturer India list",
        ]
        for c in categories:
            qs += category_competitor_queries(c)  # specific multi-angle per segment
        return qs
    angles = [
        ["lithium ion drone battery manufacturer", "LiPo drone battery maker company",
         "agriculture drone battery manufacturer India", "drone battery manufacturer China"],
        ["UAV battery manufacturer Europe", "VTOL drone battery pack supplier",
         "semi-solid state drone battery manufacturer", "high voltage drone battery pack maker"],
        ["drone battery OEM manufacturer", "industrial UAV battery supplier",
         "agri spraying drone battery factory", "drone battery manufacturer worldwide list"],
        ["smart drone battery manufacturer", "long endurance UAV battery maker",
         "drone battery pack company directory", "best drone battery brands manufacturers"],
    ]
    return angles[(round_idx - 1) % len(angles)]


def extract_candidates(
    results: list[dict], cat_by_query: dict[str, str] | None = None
) -> list[dict]:
    """Raw SERP rows → de-duped candidate competitor domains (blocklist applied).

    Returns dicts: name, website, domain, category, source_url, snippet.
    Deterministic: first occurrence of a domain wins; ordering preserved. When
    `cat_by_query` is given, each candidate is tagged with the mPower category
    whose search surfaced it (originating-search category attribution); a domain
    first seen via a non-category query gets `category=None` (Claude fills it
    later only if still blank)."""
    cat_by_query = cat_by_query or {}
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
        out.append({
            "name": name_from_domain(dom),
            "website": f"https://{dom}/",
            "domain": dom,
            "category": cat_by_query.get(r.get("query") or ""),
            "source_url": url,
            "snippet": (r.get("description") or "")[:400],
        })
    return out


_DOMAIN_NOISE = {"com", "net", "org", "co", "in", "io", "cn", "uk", "de", "us", "biz", "info"}


def name_from_domain(dom: str) -> str:
    """e.g. 'herewinpower.com' -> 'Herewinpower'; 'gens-tattu.com' -> 'Gens Tattu'."""
    if not dom:
        return "(unknown)"
    label = dom.split(".")[0]
    words = [w for w in label.replace("-", " ").replace("_", " ").split() if w not in _DOMAIN_NOISE]
    if not words:
        words = [label]
    return " ".join(w.capitalize() for w in words)[:120]


def profile_queries(name: str, domain: str) -> list[str]:
    """The line-by-line Apify enrichment pass — a SOLID multi-angle search for ONE
    competitor, run in a single google-search actor call. Designed for high recall
    on the four fields the classifier fills: identity/product, HQ country, category
    signal, and customers ("selling to"). Search snippets bypass JS/cookie walls
    that defeat a raw homepage crawl (the Danenergy failure mode), so the classifier
    is never starved of evidence.
    """
    n = (name or "").strip()
    dom = (domain or "").strip()
    qn = f'"{n}"' if n else dom
    qs = [
        f"{dom} drone battery manufacturer about",                       # identity from the site itself
        f"{qn} drone UAV lithium battery pack manufacturer",             # product / is-it-a-maker
        f"{qn} battery company headquarters country location",           # HQ country
        f"{qn} agriculture surveillance survey delivery drone battery",  # category signal (mPower segments)
        # selling-to (own site / press) — every common phrasing a competitor uses to
        # name its buyers (user tip: "Trusted Partners" / "Our Customers" sections).
        f'{qn} drone battery "our customers" OR "trusted by" OR "trusted partners" '
        f'OR clients OR clientele OR "case studies" OR "success stories" OR "who we serve"',
        f"{qn} drone battery buyers site:volza.com OR site:importyeti.com OR site:eximpedia.app",  # selling-to (trade)
    ]
    return [q for q in qs if q.strip()]


def marketplace_resolve_query(name: str) -> list[str]:
    """Name→domain resolve query for a marketplace row (IndiaMART) that has no
    own-domain. The existing google-search lane + blocklist turns the first organic
    company result into a canonical competitor domain."""
    n = (name or "").strip()
    if not n:
        return []
    return [f'"{n}" official website drone battery']


def evidence_text(pages: list[dict], search_results: list[dict]) -> str:
    """Assemble the evidence blob the classifier reads — search snippets FIRST
    (they survive cookie/JS walls), then the competitor's own crawled pages.
    Bounded length so the prompt stays cheap + focused."""
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
