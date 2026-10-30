"""Pure, deterministic helpers for Generate-Leads — no DB, no I/O, no network.

`map_person` defensively normalizes any actor record → a clean lead dict (incl.
its employer domain, for the membership gate). The `build_*_input` helpers turn
(company, anchor, titles, country) into each actor's input dict — same inputs →
same dict, always. `pick_anchor` deterministically reduces Stage-0 SERP results
to {domain, website, linkedin_url}.
"""

from __future__ import annotations

from app.leadgen import config, membership


def _first(rec: dict, *keys: str) -> str | None:
    """First non-empty string among the candidate keys (defensive)."""
    for k in keys:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _harvest_email(raw: dict) -> str | None:
    """harvestapi 'Full + email search' email — flat `email`, or `emails[]` of
    strings OR of {email/value/address} objects (shape undocumented → defensive)."""
    e = _first(raw, "email", "workEmail", "professionalEmail")
    if e:
        return e
    arr = raw.get("emails")
    if isinstance(arr, list):
        for item in arr:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                v = _first(item, "email", "value", "address")
                if v:
                    return v
    return None


def _harvest_company(raw: dict) -> str | None:
    """Employer name from harvest `currentPosition` (a LIST) or `experience[0]`."""
    cur = raw.get("currentPosition")
    if isinstance(cur, list) and cur and isinstance(cur[0], dict):
        return _first(cur[0], "companyName", "company_name", "name")
    if isinstance(cur, dict):
        return _first(cur, "companyName", "company_name", "name")
    for job in raw.get("experience") or []:
        if isinstance(job, dict):
            return _first(job, "companyName", "company_name", "name")
    return None


def _location_text(raw: dict) -> str | None:
    """Location across shapes: flat string, city/state/country, or harvest
    `location.parsed.{city,state,country}` / `location.linkedinText`."""
    loc = raw.get("location")
    if isinstance(loc, dict):
        parsed = loc.get("parsed") if isinstance(loc.get("parsed"), dict) else {}
        return (_first(parsed, "text")
                or ", ".join(x for x in [_first(parsed, "city"), _first(parsed, "state"),
                                         _first(parsed, "country")] if x) or None
                or _first(loc, "linkedinText"))
    flat = _first(raw, "location", "city", "contact_location", "geo", "locationName",
                  "13_Current_address", "14_City")
    if flat:
        return flat
    bits = [raw.get("city"), raw.get("state"), raw.get("country"),
            raw.get("14_City"), raw.get("15_Country")]
    joined = ", ".join(b.strip() for b in bits if isinstance(b, str) and b.strip())
    return joined or None


def map_person(raw: dict) -> dict | None:
    """Defensively map one raw actor record → lead fields. None if not a dict.

    Handles every engine shape this pipeline runs: Apollo search/match,
    harvestapi (currentPosition list / experience / location.parsed / emails[]),
    snipercoder email-finder (`NN_`-prefixed keys), and the paid code_crafter.
    """
    if not isinstance(raw, dict):
        return None

    first = _first(raw, "first_name", "firstName", "given_name", "02_First_name")
    last = _first(raw, "last_name", "lastName", "family_name", "03_Last_name")
    if not first and not last:
        full = _first(raw, "name", "full_name", "fullName", "01_Name")
        if full:
            parts = full.split()
            first = parts[0]
            last = " ".join(parts[1:]) if len(parts) > 1 else ""

    company = _first(raw, "organization_name", "company_name", "company", "organization",
                     "16_Company_name")
    if company is None:
        org = raw.get("organization")
        if isinstance(org, dict):
            company = _first(org, "name")
    if company is None:
        company = _harvest_company(raw)

    return {
        "first_name": first or "",
        "last_name": last or "",
        "email": _first(raw, "email", "email_address", "work_email", "04_Email")
        or _harvest_email(raw),
        "phone": _first(raw, "phone", "phone_number", "mobile", "05_Phone_number"),
        "linkedin_url": _first(
            raw, "linkedin_url", "linkedin", "linkedinUrl", "profileUrl",
            "publicProfileUrl", "06_Linkedin_url"
        ),
        "title": _first(raw, "title", "headline", "job_title", "jobTitle", "position",
                        "07_Title"),
        "location": _location_text(raw),
        "company_name": company,
        # Employer domain for the membership gate (registrable; "" when absent).
        "company_domain": membership.employer_domain(raw),
    }


# --- Stage 0: anchor resolution ---------------------------------------------
def search_queries(company_name: str, country: str | None, category: str | None) -> list[str]:
    """Deterministic SERP queries to surface a company's website + LinkedIn page.

    Includes a drone disambiguator (every customer is a drone OEM/reseller) so
    generic names ("Continental") resolve to the right entity.
    """
    base = (company_name or "").strip()
    if not base:
        return []
    loc = (country or "").strip()
    loc = "" if loc.lower() in {"", "global", "worldwide"} else loc
    cat = (category or "").strip()
    cat = "" if cat.lower() in {"", "uncategorized", "most-popular"} else cat
    web_q = " ".join(p for p in [base, "drone", cat, loc, "official website"] if p)
    return [web_q, f"{base} linkedin company"]


def build_search_input(queries: list[str], *, results: int | None = None, country_code: str = "") -> dict:
    """The exact google-search-scraper input (deterministic)."""
    inp: dict = {
        "queries": "\n".join(queries),
        "resultsPerPage": int(results if results is not None else config.RESULTS_PER_QUERY),
        "maxPagesPerQuery": 1,
        "saveHtml": False,
        "mobileResults": False,
    }
    if country_code:
        inp["countryCode"] = country_code
    return inp


def _linkedin_company_url(url: str) -> str | None:
    """Return a canonical linkedin.com/company/<slug> URL if `url` is one."""
    d = membership.normalize_domain(url)
    if d != "linkedin.com":
        return None
    low = url.lower()
    if "/company/" not in low:
        return None
    return url.split("?", 1)[0].split("#", 1)[0]


def pick_anchor(results: list[dict]) -> dict:
    """Deterministically reduce SERP organic results → {domain, website, linkedin_url}.

    domain/website = the FIRST organic result whose registrable domain is not a
    social/directory host; linkedin_url = the FIRST linkedin.com/company/ result.
    Order is preserved (deterministic). Missing pieces → "".
    """
    domain = website = linkedin_url = ""
    for r in results or []:
        url = r.get("url") if isinstance(r, dict) else None
        if not isinstance(url, str) or not url.strip():
            continue
        if not linkedin_url:
            li = _linkedin_company_url(url)
            if li:
                linkedin_url = li
        reg = membership.registrable(url)
        if reg and reg not in config.SOCIAL_BLOCKLIST and not domain:
            domain = reg
            website = url.split("?", 1)[0].split("#", 1)[0]
    return {"domain": domain, "website": website, "linkedin_url": linkedin_url}


# --- per-engine input builders ----------------------------------------------
def build_apollo_input(
    company_name: str, anchor_domain: str | None, titles: list[str], country: str | None,
    *, results: int | None = None,
) -> dict:
    """Apollo leads-finder input. PRIMARY engine — anchored on `company_domain`
    (exact employer constraint) when a domain is known; falls back to the company
    NAME keyword only when no domain resolved (KI-10: keyword is description-OR)."""
    title_tokens = sorted({t.strip().lower() for t in titles if t and t.strip()})
    inp: dict = {
        "fetch_count": int(results if results is not None else config.RESULTS_PER_QUERY),
    }
    if title_tokens:
        inp["contact_job_title"] = title_tokens
    dom = membership.registrable(anchor_domain)
    if dom:
        inp["company_domain"] = [dom]
    else:
        name = (company_name or "").strip()
        if name:
            inp["company_keywords"] = [name]
    loc = (country or "").strip().lower()
    if loc and loc != "global":
        inp["contact_location"] = [loc]
    return inp


def build_linkedin_input(
    company_name: str, titles: list[str], country: str | None, *,
    li_url: str | None = None, results: int | None = None,
) -> dict:
    """LinkedIn profile-search (engine 3, REVIVED). Anchored on the company
    LinkedIn URL via `currentCompanies` when known (was `companyName`, which the
    actor IGNORES → company-unconstrained → 0 verified). `Full + email search`
    returns work emails. The membership gate still drops any stray."""
    inp: dict = {
        "currentJobTitles": [t for t in titles if t and t.strip()][:50],
        "maxItems": int(results if results is not None else config.RESULTS_PER_QUERY),
        "profileScraperMode": "Full + email search",
    }
    url = (li_url or "").strip()
    if url:
        inp["currentCompanies"] = [url]
    else:
        # No LinkedIn URL resolved → fuzzy company-name search (gate cleans up).
        inp["searchQuery"] = (company_name or "").strip()
    loc = (country or "").strip()
    if loc and loc.lower() not in {"global", "worldwide"}:
        inp["locations"] = [loc]
    return inp


def build_company_employees_input(
    company_or_url: str, titles: list[str], *, results: int | None = None
) -> dict:
    """LinkedIn company-employees (engine 2, FIXED). `companies` takes the
    LinkedIn company URL (preferred) or name. `maxEmployees` is NOT a valid key
    (it caused HTTP 400) — removed. `Full + email search` adds work emails."""
    n = int(results if results is not None else config.RESULTS_PER_QUERY)
    inp: dict = {
        "companies": [company_or_url] if company_or_url else [],
        "maxItems": n,
        "profileScraperMode": "Full + email search ($12 per 1k)",
    }
    tl = [t for t in titles if t and t.strip()][:20]
    if tl:
        inp["jobTitles"] = tl
    return inp


def build_email_finder_input(domain: str, category: str, max_leads: int) -> dict:
    """snipercoder decision-maker email-finder (engine 4, NEW). One category per
    call; returns `NN_`-prefixed records incl. `04_Email` + `05_Phone_number` +
    `17_Query_domain` (= the employer domain, for the membership gate)."""
    return {
        "domain": membership.registrable(domain) or (domain or "").strip(),
        "decision_maker_category": category,
        "max_leads_to_find": int(max_leads),
    }


# Back-compat: the old single-fallback builder name → Apollo input by domain.
def build_fallback_input(
    company_name: str, titles: list[str], country: str | None, *,
    anchor_domain: str | None = None, results: int | None = None,
) -> dict:
    return build_apollo_input(
        company_name, anchor_domain, titles, country, results=results
    )
