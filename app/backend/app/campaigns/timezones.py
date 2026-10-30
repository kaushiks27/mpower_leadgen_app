"""Deterministic country → IANA send-timezone map (08062026_cr CR-5).

A campaign's send timezone is DERIVED, never hand-picked: it is the timezone of
the majority country across the campaign's leads (alphabetical country tiebreak).
This module owns the pure, deterministic mapping — no LLM, no float, same input →
same output (exact-math rule). Multi-timezone countries resolve to ONE
business-canonical zone (e.g. USA → America/New_York, India → Asia/Kolkata).

Unknown / blank countries fall back to the mPower default (Asia/Kolkata) so a
campaign always has a valid IANA zone to push to Instantly.
"""

from __future__ import annotations

DEFAULT_TZ = "Asia/Kolkata"

# Lowercased country/alias → canonical IANA zone. Covers the countries mPower's
# customer base spans; extend as new markets appear. Keys are normalized
# (lowercase, trimmed) before lookup so "India", "india", " INDIA " all match.
COUNTRY_TZ: dict[str, str] = {
    "india": "Asia/Kolkata",
    "bharat": "Asia/Kolkata",
    "united states": "America/New_York",
    "united states of america": "America/New_York",
    "usa": "America/New_York",
    "us": "America/New_York",
    "u.s.": "America/New_York",
    "u.s.a.": "America/New_York",
    "america": "America/New_York",
    "canada": "America/Toronto",
    "united kingdom": "Europe/London",
    "uk": "Europe/London",
    "u.k.": "Europe/London",
    "england": "Europe/London",
    "great britain": "Europe/London",
    "ireland": "Europe/Dublin",
    "germany": "Europe/Berlin",
    "france": "Europe/Paris",
    "spain": "Europe/Madrid",
    "italy": "Europe/Rome",
    "netherlands": "Europe/Amsterdam",
    "the netherlands": "Europe/Amsterdam",
    "belgium": "Europe/Brussels",
    "switzerland": "Europe/Zurich",
    "austria": "Europe/Vienna",
    "sweden": "Europe/Stockholm",
    "norway": "Europe/Oslo",
    "denmark": "Europe/Copenhagen",
    "finland": "Europe/Helsinki",
    "poland": "Europe/Warsaw",
    "portugal": "Europe/Lisbon",
    "greece": "Europe/Athens",
    "turkey": "Europe/Istanbul",
    "russia": "Europe/Moscow",
    "ukraine": "Europe/Kyiv",
    "uae": "Asia/Dubai",
    "united arab emirates": "Asia/Dubai",
    "saudi arabia": "Asia/Riyadh",
    "qatar": "Asia/Qatar",
    "israel": "Asia/Jerusalem",
    "pakistan": "Asia/Karachi",
    "bangladesh": "Asia/Dhaka",
    "sri lanka": "Asia/Colombo",
    "nepal": "Asia/Kathmandu",
    "china": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong",
    "taiwan": "Asia/Taipei",
    "japan": "Asia/Tokyo",
    "south korea": "Asia/Seoul",
    "korea": "Asia/Seoul",
    "singapore": "Asia/Singapore",
    "malaysia": "Asia/Kuala_Lumpur",
    "indonesia": "Asia/Jakarta",
    "thailand": "Asia/Bangkok",
    "vietnam": "Asia/Ho_Chi_Minh",
    "philippines": "Asia/Manila",
    "australia": "Australia/Sydney",
    "new zealand": "Pacific/Auckland",
    "south africa": "Africa/Johannesburg",
    "nigeria": "Africa/Lagos",
    "kenya": "Africa/Nairobi",
    "egypt": "Africa/Cairo",
    "brazil": "America/Sao_Paulo",
    "mexico": "America/Mexico_City",
    "argentina": "America/Argentina/Buenos_Aires",
    "chile": "America/Santiago",
    "colombia": "America/Bogota",
}


def _norm(country: str | None) -> str:
    return " ".join((country or "").strip().lower().split())


def timezone_for_country(country: str | None) -> str:
    """Map one country to its canonical IANA zone (DEFAULT_TZ when unknown/blank)."""
    return COUNTRY_TZ.get(_norm(country), DEFAULT_TZ)


def majority_country(countries: list[str]) -> str | None:
    """The most-frequent non-blank country; alphabetical tiebreak. None if empty.

    Deterministic: counts by normalized display value, and on a frequency tie
    returns the alphabetically-first ORIGINAL country string (CR-5 / decision Q15).
    """
    cleaned = [c.strip() for c in countries if c and c.strip()]
    if not cleaned:
        return None
    counts: dict[str, int] = {}
    for c in cleaned:
        counts[c] = counts.get(c, 0) + 1
    # Sort by (-count, country) so the highest count wins, alphabetical on ties.
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def majority_timezone(countries: list[str]) -> str:
    """Derive the campaign send timezone from its leads' countries (CR-5).

    Majority country (alphabetical tiebreak) → canonical IANA zone. Empty → the
    mPower default. No LLM, no float — pure + deterministic.
    """
    top = majority_country(countries)
    return timezone_for_country(top)
