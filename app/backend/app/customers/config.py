"""Customer-discovery configuration — deterministic caps + source constants.

Customers = companies mPower would SELL drone batteries TO, in two types:
  * OEM        — a drone MANUFACTURER (builds drones, buys battery packs). NOT a
                 battery manufacturer (that is a competitor, not a customer).
  * Reseller / Distributor — of drone batteries / mPower's product categories.

Spend is unlimited this session but a runaway-loop backstop (MAX_ACTOR_CALLS)
guards the adaptive loop. All caps owned by Python — the LLM never decides a stop.
A SMOKE override (env CUSTOMERS_SMOKE=1) shrinks every cap so a live self-test is
cheap.
"""

from __future__ import annotations

import os

_SMOKE = (os.environ.get("CUSTOMERS_SMOKE", "").strip().lower() in {"1", "true", "yes"})

# --- adaptive discovery loop -------------------------------------------------
MAX_DISCOVERY_ROUNDS = 2 if _SMOKE else 6
PLATEAU_THRESHOLD = 2 if _SMOKE else 3          # < this many NEW domains → stop
RESULTS_PER_QUERY = 10 if _SMOKE else 20
MAX_QUERIES_PER_ROUND = 3 if _SMOKE else 24
MAX_CANDIDATES = 4 if _SMOKE else None          # None = no cap (exhaustive); SMOKE bounds cost

# --- per-customer enrichment (stages 2→5) ------------------------------------
STAGE2_CONCURRENCY = 6                            # concurrent enrich+classify pipelines
CRAWL_PAGES_PER_CUSTOMER = 1 if _SMOKE else 4     # homepage + a few pages for signal
ENRICH_RESULTS_PER_QUERY = 6 if _SMOKE else 10    # results per profile-search query

# --- runaway backstop (safety, NOT a budget) ---------------------------------
MAX_ACTOR_CALLS = 30 if _SMOKE else 2000

# --- Apify actors ------------------------------------------------------------
SEARCH_ACTOR = "apify~google-search-scraper"      # discovery
CRAWL_ACTOR = "apify~website-content-crawler"     # homepage signal + type

# --- S-MS1 multi-source lanes (run ALONGSIDE the Google lane in Stage 1) ------
# 6 smoke-proven actors (Kompass + Made-in-China dropped — KI-29/30). Each lane's
# adapter (input/output) lives in `lanes.py`; orchestration in `apify_client`.
LANES_ENABLED = (os.environ.get("CUSTOMERS_LANES", "1").strip().lower() not in {"0", "false", "no"})

# Default region per lane (lane query inputs differ — see lanes.build_input).
LANE_REGION_DEFAULT: dict[str, str | None] = {
    "maps": None,            # global Maps
    "linkedin": None,        # global company search
    "indiamart": "India",    # India marketplace
    "thomasnet": "NA",       # North-America directory
    "europages": "DE",       # pan-EU; DE seed (ISO2 country filter)
    "wlw": "DE",             # DACH (DE/AT/CH)
}
# Per-lane result cap + how many of EACH ROUND's queries fan out to the lanes
# (option-1: Claude's expanded phrases hit every lane every round → max coverage).
# Single-query lanes issue one actor call per query, so this bounds per-round calls.
# SMOKE shrinks both so a live self-test stays cheap.
LANE_MAX_ITEMS = 8 if _SMOKE else 60
LANE_MAX_QUERIES_PER_ROUND = 1 if _SMOKE else 4
# ThomasNet (residential proxy) is slow (~222s live) — give it a generous timeout.
LANE_TIMEOUT_DEFAULT = 180.0
LANE_TIMEOUT = {"thomasnet": 360.0}

# --- Stage 6 contact enrichment (Apollo org + people → MillionVerifier gate) ---
# Only eligible (Sure/Likely) rows missing a contact are enriched (paid, narrow).
ENRICH_ELIGIBLE_BANDS = ("Sure", "Likely")
ENRICH_CONCURRENCY = 5
APOLLO_PEOPLE_PER_PAGE = 5        # over-fetch a few; take the first work-email match
ENRICH_TIMEOUT = 60.0
# Per-run cap so each Sync enriches the NEXT batch of eligible rows (incremental, like
# discovery) instead of all of them at once. A row is enriched AT MOST ONCE (the attempt
# stamps email_quality) — never re-tried, never re-spends credits (mirrors S-6).
ENRICH_MAX_PER_RUN = 5 if _SMOKE else 50

# --- Claude models (split by task, OP #10) -----------------------------------
# Country + type + name are a terse EXTRACTION from crawl evidence — a cheaper
# model is fine. The genuine-customer BAND stays on the strongest model.
EXTRACT_MODEL = os.environ.get("CUSTOMERS_EXTRACT_MODEL", "claude-haiku-4-5-20251001")

# --- website resolve (stage 2) ----------------------------------------------
WEBRESOLVE_TIMEOUT = 8.0
WEBRESOLVE_CONCURRENCY = 8

# --- genuine-customer bands. Sure+Likely = a trusted prospective customer. ----
BANDS = ("Sure", "Likely", "Unsure", "No")
ELIGIBLE_BANDS = ("Sure", "Likely")

# --- customer types (Type column) -------------------------------------------
CTYPES = ("OEM", "Reseller", "Distributor")

# --- discovery source mix (two lanes per category: OEM + channel) -------------
# Each tuple: (label shown in dev-reference, query hint).
DISCOVERY_SOURCES = (
    ("Drone-OEM lists (manufacturers who BUY packs)", "top drone UAV manufacturers companies list"),
    ("Agriculture / surveillance drone makers", "agriculture surveillance survey delivery drone manufacturer"),
    ("Drone-battery distributors / resellers", "drone battery distributor reseller supplier"),
    ("B2B directories — IndiaMART/TradeIndia (channel)", "site:indiamart.com OR site:tradeindia.com drone battery distributor"),
    ("General web search (OEM + channel)", "drone manufacturer OR drone battery distributor company"),
)

# "Type" enrichment sources (best-effort signal for OEM vs Reseller vs Distributor).
TYPE_SOURCES = (
    "company website (about / products — do they BUILD drones or RESELL parts?)",
    "B2B directory + distributor-network / authorized-dealer pages",
)
