"""Pure identifier normalization — no DB, no I/O, fully deterministic.

Both suppression matching AND lead dedup must canonicalize identifiers the same
way, or "John@X.com" and "john@x.com" would be treated as different people. This
is the single source of truth for that canonicalization; `leads.dedup` imports
it (one-way: leads -> suppression).
"""

from __future__ import annotations

import re


def normalize_email(email: str | None) -> str | None:
    """Lowercase + trim. Returns None for empty/blank input."""
    if not email:
        return None
    e = email.strip().lower()
    return e or None


# Matches an optional scheme/host and captures the canonical "in/<slug>" path.
_LI_IN = re.compile(r"(?:^|/)in/([^/?#]+)", re.IGNORECASE)


def normalize_linkedin(url: str | None) -> str | None:
    """Canonicalize a LinkedIn profile URL to `linkedin.com/in/<slug>`.

    Strips scheme, `www.`/country subdomain, query, fragment, trailing slash, and
    lowercases. A bare slug (no `/in/`) is treated as already-canonical text and
    lowercased/trimmed so non-URL identifiers still match consistently. Returns
    None for empty/blank input.
    """
    if not url:
        return None
    raw = url.strip()
    if not raw:
        return None
    m = _LI_IN.search(raw)
    if m:
        slug = m.group(1).strip().lower().rstrip("/")
        return f"linkedin.com/in/{slug}" if slug else None
    # No recognizable /in/ segment — fall back to a trimmed lowercase form.
    return raw.lower().rstrip("/") or None
