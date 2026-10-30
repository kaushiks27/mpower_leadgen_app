"""Pure, deterministic Apify-input builder — no DB, no I/O, no network.

Maps a campaign's human-readable targeting (decision-maker roles + geography +
target-customer category) onto the `code_crafter/leads-finder` actor's input
schema so the search is "spot-on" for the segment. Same inputs -> same dict,
always (sorted, de-duped tokens). Unit-tested in isolation.

Actor field mapping (see references: leads-finder input schema):
  - roles            -> contact_job_title   (individual title tokens)
  - geography        -> contact_location    (region/country)
  - ICP keywords     -> company_keywords    (drone-anchored buyer-type keywords,
                                             from each ICP filter's `value`; the
                                             sole company signal — S-5d)
  - per-run cap      -> fetch_count          (how many leads to pull this run)

`company_keywords` is OR-matched by the actor against company descriptions, so
every keyword MUST stay drone-anchored — generic tokens ("manufacturer") match
any company. The target category is deliberately NOT sent (would broaden).

`active_90d` has NO field in this Apollo-sourced actor (it has no recent-activity
filter), so it is accepted but NOT applied here — only a LinkedIn-native actor
would honor it (KI-7). Kept in the signature so the service/router stay stable
when such an actor is wired later.
"""

from __future__ import annotations


def split_role_titles(role_names: list[str]) -> list[str]:
    """Split slash-grouped role buckets into individual job-title tokens.

    Catalog role names group synonyms (e.g. "Procurement / Sourcing /
    Supply-chain"); the actor's `contact_job_title` wants discrete titles. Split
    on '/', trim, lowercase, drop blanks, de-dupe, and sort for determinism.
    """
    tokens: set[str] = set()
    for name in role_names:
        for part in (name or "").split("/"):
            t = part.strip().lower()
            if t:
                tokens.add(t)
    return sorted(tokens)


def _company_keywords(icp_keywords: list[str] | None) -> list[str]:
    """Flatten ICP keyword specs into Apify `company_keywords` tokens.

    Each spec is the ICP filter's drone-anchored `value` (e.g. "drone
    manufacturer, drone OEM, UAV manufacturer"), split on COMMA into discrete
    OR-matched keywords. NB: we do NOT split on "/" — that was the S-5b bug:
    splitting "Drone OEMs / Manufacturers" emitted the generic token
    "Manufacturers", which Apollo OR-matches against ANY manufacturer, dropping
    the "drone" anchor (P0 fixed in S-5d). The target category is intentionally
    NOT included — ICP keywords are the sole, strictly-drone company signal.
    De-duped case-insensitively, first-occurrence order preserved; deterministic
    given deterministic input.
    """
    seen: set[str] = set()
    out: list[str] = []
    for spec in icp_keywords or []:
        for part in (spec or "").split(","):
            kw = part.strip()
            low = kw.lower()
            if kw and low not in seen:
                seen.add(low)
                out.append(kw)
    return out


def build_search_input(
    *,
    role_names: list[str],
    geography: str | None,
    icp_keywords: list[str] | None = None,
    fetch_count: int,
    active_90d: bool = True,  # accepted; inert for this actor (KI-7)
) -> dict:
    """Build the deterministic actor-input dict for a campaign's segment."""
    if fetch_count < 1:
        raise ValueError("fetch_count must be >= 1")

    input_: dict = {"fetch_count": fetch_count}

    titles = split_role_titles(role_names)
    if titles:
        input_["contact_job_title"] = titles

    geo = (geography or "").strip().lower()
    if geo and geo != "global":
        # "Global" = no location constraint (search everywhere). Apify's
        # `contact_location` is a strict lowercase country enum, so the token is
        # lowercased here (mirrors the role-title handling above). NB: this fixes
        # casing only — alias mismatches (e.g. "USA" vs "united states") still
        # fail and need a name->enum map (KI: geography alias mapping).
        input_["contact_location"] = [geo]

    keywords = _company_keywords(icp_keywords)
    if keywords:
        input_["company_keywords"] = keywords

    return input_
