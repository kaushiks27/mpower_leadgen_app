"""Deterministic lead-identity dedup — pure functions, no DB, no I/O.

Identity precedence (locked Q10): LinkedIn URL -> email -> name+company. The
first available tier wins; the key is tier-prefixed so two leads can never
collide across tiers (an email and a name+company that hash alike stay
distinct). Same input -> same key, always (sha256). Normalization is shared with
suppression via `suppression.normalize` (one-way import: leads -> suppression).
"""

from __future__ import annotations

import hashlib

from app.suppression.normalize import normalize_email, normalize_linkedin


def _norm_text(s: str | None) -> str:
    """Collapse whitespace + lowercase for name/company hashing."""
    if not s:
        return ""
    return " ".join(s.strip().lower().split())


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def dedup_key(
    *,
    first_name: str | None,
    last_name: str | None,
    email: str | None,
    linkedin_url: str | None,
    company_name: str | None,
) -> str:
    """Return the deterministic global dedup key for a lead identity.

    Raises ValueError when no identifier at all is present (no LinkedIn, no
    email, and no name+company) — such a lead cannot be deduped and must be
    rejected by the caller.
    """
    li = normalize_linkedin(linkedin_url)
    if li:
        return "li:" + _sha(li)

    em = normalize_email(email)
    if em:
        return "em:" + _sha(em)

    name = (_norm_text(first_name) + " " + _norm_text(last_name)).strip()
    company = _norm_text(company_name)
    if name and company:
        return "nc:" + _sha(name + "|" + company)

    raise ValueError(
        "lead has no usable identifier (need LinkedIn URL, email, or name+company)"
    )
