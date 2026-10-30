"""Canonical mPower drone-segment normalizer (shared infrastructure).

The brain catalog stores bare segment labels ("Mapping", "Survey", "Delivery")
and some operational labels ("B2B sales", "Certification", "Recycling"). Used raw
as a search anchor these drift off-domain — a search for "Mapping manufacturer"
returns Google-Maps products, "Surveillance" returns CCTV firms. This module turns
a raw catalog category into a DRONE-anchored segment phrase, or None when the
category is not a drone product segment.

Shared by Competitors AND Customers discovery so both anchor identically — one
source of truth, no drift. Infrastructure (not a feature), so feature modules may
import it one-way per OP #11.

Guarantees, in order:
  1. Non-segment / operational labels → None (issue no per-category query; the
     global staple queries still cover them).
  2. Strip "battery / batteries / pack(s)" so the phrase names the DRONE SEGMENT,
     not the battery (the per-lane tail re-adds "battery" where it belongs).
  3. Inject "drone" when absent so EVERY query is on-domain.
"""

from __future__ import annotations

import re

# Catalog categories that are NOT a drone product segment — a per-category
# discovery search on these yields off-domain noise, so they issue no query.
# (lowercased exact match against the catalog category string)
NON_SEGMENT = {
    "adjacent market",
    "b2b sales",
    "certification",
    "channel",
    "custom packs",
    "inverter batteries",
    "r&d",
    "recycling",
    "uncategorized",
    "most-popular",
}

_BATTERY_NOISE = re.compile(r"\b(batteries|battery|packs|pack)\b", re.IGNORECASE)


def segment_phrase(category: str | None) -> str | None:
    """Raw catalog category → a DRONE-anchored segment phrase, or None to skip.

    Examples:
      "Mapping"                     -> "Mapping drone"
      "Surveillance drone batteries"-> "Surveillance drone"
      "Agriculture Spraying"        -> "Agriculture Spraying drone"
      "Recycling" / "B2B sales"     -> None  (not a drone product segment)
    Deterministic + pure (unit-testable, no I/O)."""
    c = (category or "").strip()
    if not c or c.lower() in NON_SEGMENT:
        return None
    s = " ".join(_BATTERY_NOISE.sub(" ", c).split())
    if not s:
        return None
    low = s.lower()
    if "drone" in low or "uav" in low:
        return s
    return f"{s} drone"
