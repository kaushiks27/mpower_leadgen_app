"""Competitor-discovery configuration — deterministic caps + source constants.

Spend is unlimited this session (Amendment 2026-06-06) but a runaway-loop
backstop (MAX_ACTOR_CALLS) guards against an infinite adaptive loop. All caps
are owned by Python — the LLM never decides a stop. A SMOKE override (env
COMPETITORS_SMOKE=1) shrinks every cap so a live self-test is cheap.
"""

from __future__ import annotations

import os

_SMOKE = (os.environ.get("COMPETITORS_SMOKE", "").strip().lower() in {"1", "true", "yes"})

# --- adaptive discovery loop -------------------------------------------------
# Each round runs a batch of Claude-proposed queries; the loop stops when a round
# adds fewer than PLATEAU_THRESHOLD new domains (coverage plateau) or MAX_ROUNDS
# is hit — whichever first. Deterministic Python owns the dedup/count/stop.
MAX_DISCOVERY_ROUNDS = 2 if _SMOKE else 6
PLATEAU_THRESHOLD = 2 if _SMOKE else 3          # < this many NEW domains → stop
RESULTS_PER_QUERY = 10 if _SMOKE else 20
MAX_QUERIES_PER_ROUND = 3 if _SMOKE else 24
MAX_CANDIDATES = 4 if _SMOKE else None          # None = no cap (exhaustive); SMOKE bounds cost

# --- per-competitor enrichment (Stage 2) -------------------------------------
# Each competitor gets a line-by-line Apify pass: ONE multi-angle profile search
# (identity/product/country/category/customers) + ONE homepage crawl → fed to the
# classifier. 2 actor calls per competitor.
STAGE2_CONCURRENCY = 6                            # concurrent enrich+classify pipelines
CRAWL_PAGES_PER_COMPETITOR = 2 if _SMOKE else 8   # homepage + evidence pages for selling-to
ENRICH_RESULTS_PER_QUERY = 6 if _SMOKE else 10    # results per profile-search query
MINE_TRADE_DATA = not _SMOKE                      # include trade-record queries in the pass

# --- runaway backstop (safety, NOT a budget) ---------------------------------
# ~2 calls/competitor + discovery + lanes; generous headroom so a big exhaustive
# run (hundreds of competitors) completes without the loop guard tripping early.
MAX_ACTOR_CALLS = 40 if _SMOKE else 3000

# --- Apify actors ------------------------------------------------------------
# Apify API paths use '~' in slugs (owner~name), not '/'.
SEARCH_ACTOR = "apify~google-search-scraper"      # discovery
CRAWL_ACTOR = "apify~website-content-crawler"     # homepage signal + customers

# --- Selling-to crawler (critical-2: stronger than raw cheerio) --------------
# cheerio is fast but does NOT render JS — modern competitor sites hide their
# clients / case-study / "trusted by" sections behind JS or cookie walls (the
# Danenergy failure mode), starving the classifier of selling-to evidence.
# playwright:adaptive renders JS where needed (and falls back to raw HTTP on
# static pages, so it stays cheap), removes cookie warnings, and we steer it
# toward the customer-evidence pages with include globs.
CRAWLER_TYPE = os.environ.get("COMPETITORS_CRAWLER_TYPE", "playwright:adaptive")
CRAWL_DYNAMIC_WAIT_SECS = 8                       # let JS-rendered client lists load
CRAWL_REMOVE_COOKIE_WARNINGS = True
CRAWL_MAX_DEPTH = 2
# Customer-evidence pages to FOLLOW beyond the homepage (selling-to signal lives
# here). Globs match any path containing these tokens on the competitor's domain.
# Tokens cover the common page-slug variants competitors use to name their buyers
# (user tip: "Trusted Partners" / "Our Customers" sections). Matched case-insensitively
# as substrings, so "our-customers", "trusted-partners", "clientele" all hit.
CRAWL_INCLUDE_GLOB_TOKENS = (
    "customer", "client", "clientele", "case-stud", "case_stud", "casestud",
    "reference", "testimonial", "partner", "trusted", "brand", "about",
    "industry", "industries", "portfolio", "success", "who-we-serve", "markets",
)

# --- S-CR2 multi-source lanes (run ALONGSIDE the Google lane in Stage 1) ------
# Module-local mirror of the customer lane set (OP#11 — no feature→feature import).
# The lane adapters are query-agnostic company finders, so feeding them competitor
# (battery-maker) queries discovers competitors, not customers.
LANES_ENABLED = (
    os.environ.get("COMPETITORS_LANES", "1").strip().lower() not in {"0", "false", "no"}
)
LANE_REGION_DEFAULT: dict[str, str | None] = {
    "maps": None,            # global Maps
    "linkedin": None,        # global company search
    "indiamart": "India",    # India marketplace
    "thomasnet": "NA",       # North-America directory
    "europages": "DE",       # pan-EU; DE seed (ISO2 country filter)
    "wlw": "DE",             # DACH (DE/AT/CH)
}
LANE_MAX_ITEMS = 8 if _SMOKE else 50              # fallback per-source cap (knob overrides)
LANE_MAX_QUERIES_PER_ROUND = 1 if _SMOKE else 4
LANE_TIMEOUT_DEFAULT = 180.0
LANE_TIMEOUT = {"thomasnet": 360.0}              # residential proxy → slow

# --- Claude models (split by task, OP #10) -----------------------------------
# Country + selling-to + name are a terse EXTRACTION from crawl evidence — a
# cheaper/faster model is fine. The true-competitor BAND is the load-bearing-ish
# judgment and stays on the strongest model (claude_classify.DEFAULT_MODEL).
EXTRACT_MODEL = os.environ.get("COMPETITORS_EXTRACT_MODEL", "claude-haiku-4-5-20251001")

# --- website resolve (stage 2) ----------------------------------------------
# Cheap httpx redirect-follow to find a company's canonical URL — NO Apify spend.
WEBRESOLVE_TIMEOUT = 8.0
WEBRESOLVE_CONCURRENCY = 8

# --- SalesPath bands (Q9). Sure+Likely = a trusted direct competitor. --------
BANDS = ("Sure", "Likely", "Unsure", "No")
ELIGIBLE_BANDS = ("Sure", "Likely")

# --- discovery source mix (the 7 researched + user-approved sources) ----------
# Each tuple: (label shown in dev-reference, query suffix/site-filter hint).
DISCOVERY_SOURCES = (
    ("Curated top-manufacturer lists", "top drone battery manufacturers list"),
    ("B2B directories — Alibaba/Made-in-China", "site:alibaba.com OR site:made-in-china.com drone battery manufacturer"),
    ("B2B directories — IndiaMART/TradeIndia", "site:indiamart.com OR site:tradeindia.com drone battery manufacturer"),
    ("General web search", "drone battery pack manufacturer"),
    ("Google Maps / local listings", "drone battery manufacturer company"),
)

# "Selling-to" enrichment sources (best-effort; blank + note when empty).
SELLING_TO_SOURCES = (
    "competitor website (case studies / clients / testimonials)",
    "public import/export trade records (Volza / ImportYeti / Eximpedia / Seair)",
)
