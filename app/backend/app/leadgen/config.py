"""Generate-Leads engine configuration — deterministic caps + source constants.

The Generate-Leads engine finds DECISION-MAKER people inside mPower's existing
prospective-customer companies (the Customers brain) and turns them into leads:
LinkedIn-first discovery, fallback actors, an optional Claude "widen" of search
terms for thin results, dedup into the Leads table, then Apollo enrich + email
verify. All caps + stops are owned by Python — the LLM never decides a number or
a pipeline state; it only proposes ADDITIONAL job-title search terms (advisory).

A SMOKE override (env LEADGEN_SMOKE=1, or ENV=test/smoke) shrinks every cap so a
live self-test stays cheap.
"""

from __future__ import annotations

import os

_ENV = (os.environ.get("ENV", "").strip().lower())
_SMOKE = (
    os.environ.get("LEADGEN_SMOKE", "").strip().lower() in {"1", "true", "yes"}
    or _ENV in {"test", "smoke"}
)

# --- Apify actors -----------------------------------------------------------
# Stage 0 anchor resolver: SERP scraper → company domain + website + LinkedIn URL.
SEARCH_ACTOR = os.environ.get("LEADGEN_SEARCH_ACTOR", "apify~google-search-scraper")
# Engine 1 (PRIMARY): Apollo-sourced finder — queried by company_domain + titles.
APOLLO_ACTOR = os.environ.get("LEADGEN_APOLLO_ACTOR", "code_crafter~leads-finder")
# Engine 2: LinkedIn company-employees (anchored on the company LinkedIn URL/name).
COMPANY_EMPLOYEES_ACTOR = os.environ.get(
    "LEADGEN_COMPANY_EMPLOYEES_ACTOR", "harvestapi~linkedin-company-employees"
)
# Engine 3 (revived): LinkedIn people search — now anchored on the company
# LinkedIn URL via `currentCompanies` (the membership gate still drops strays).
LINKEDIN_ACTOR = os.environ.get("LEADGEN_LINKEDIN_ACTOR", "harvestapi~linkedin-profile-search")
# Engine 4 (NEW): decision-maker email-finder by domain → emails + PHONES. Replaces
# the RETIRED `dominic-quaiser~decision-maker-name-email-extractor` website crawler.
EMAIL_FINDER_ACTOR = os.environ.get(
    "LEADGEN_EMAIL_FINDER_ACTOR", "snipercoder~decision-maker-email-finder"
)
# Back-compat: keep the old name pointing at the new actor so any stale import
# resolves to a live actor (the retired crawler would HTTP-404).
DOMAIN_FINDER_ACTOR = EMAIL_FINDER_ACTOR
# Back-compat alias (old single-fallback name; the Apollo engine is the successor).
FALLBACK_ACTORS = [APOLLO_ACTOR]

# Apollo-native FREE people-search candidates pulled per company (over-fetch — free).
APOLLO_SEARCH_PER_PAGE = 10 if _SMOKE else 25
# snipercoder email-finder leads pulled per decision-maker category, per company.
EMAIL_FINDER_PER_CATEGORY = 5 if _SMOKE else 15

# Registrable domains that are NEVER a company's own site — skipped when picking
# the Stage-0 anchor domain from SERP organic results (deterministic).
SOCIAL_BLOCKLIST = frozenset({
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "wikipedia.org", "crunchbase.com", "glassdoor.com",
    "indeed.com", "bloomberg.com", "zoominfo.com", "google.com", "goo.gl",
    "apollo.io", "pinterest.com", "tiktok.com", "reddit.com", "medium.com",
    "amazon.com", "yelp.com", "mapquest.com", "f6s.com", "pitchbook.com",
})

# --- widen (Claude advisory job-title proposal) -----------------------------
# Stage-1 LinkedIn hits BELOW this → ask Claude for extra title terms once.
WIDEN_THRESHOLD = 3
WIDEN_MODEL = os.environ.get("LEADGEN_WIDEN_MODEL", "claude-haiku-4-5-20251001")

# --- run caps (deterministic; SMOKE shrinks them) ---------------------------
DEFAULT_RUN_CAP = 20 if _SMOKE else 200       # total leads created across all customers
MAX_ACTOR_CALLS = 20 if _SMOKE else 2000      # runaway-loop backstop (safety, not a budget)
RESULTS_PER_QUERY = 5 if _SMOKE else 25       # people pulled per actor query
PER_CUSTOMER_CAP = 10 if _SMOKE else 50       # max leads created per single customer

# --- customer types (the Type filter) ---------------------------------------
TYPES = ("OEM", "Reseller", "Distributor")

# --- staged-job popup labels (job.detail JSON `stage` → label) --------------
STAGE_LABELS = {
    1: "Resolve domain (Apollo + web)",
    2: "Discover (Apollo + LinkedIn + email-finder)",
    3: "Membership check",
    4: "Dedup → Leads",
    5: "Apollo enrich (bulk)",
    6: "Verify emails",
}
