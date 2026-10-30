"""Deterministic company-membership gate — pure functions, no DB, no I/O.

THE load-bearing fix for KI-26: a person scraped for customer X is kept ONLY if
their CURRENT employer matches X. Matching is deterministic — registrable-domain
equality (strongest) OR normalized company-name / alias match (tolerance for
"DSLRPros LLC" == "DSLRPros"). Anything without a positive match is a MISMATCH
and gets dropped (the user chose "treat the company name religiously").

CLAUDE.md exact-math: this module decides inclusion deterministically. Claude may
PROPOSE extra name aliases (advisory, fed in via `aliases`) but never decides the
verdict here — same input → same verdict, always.
"""

from __future__ import annotations

import re

# Legal-form suffixes stripped before name comparison (so "Acme Inc" == "Acme").
_LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "llp", "ltd", "limited", "pvt", "private",
    "pte", "plc", "corp", "corporation", "co", "company", "gmbh", "ag", "sa",
    "srl", "bv", "nv", "oy", "ab", "as", "pty", "sas", "kg", "kk", "spa",
    "group", "holdings", "technologies", "technology", "tech", "systems",
    "solutions", "industries", "international", "global", "labs", "studio",
}
# Second-level domain labels that combine with a country TLD (foo.co.in).
_SLD = {"co", "com", "net", "org", "gov", "edu", "ac", "go", "or", "ne"}


def normalize_domain(url_or_domain: str | None) -> str:
    """Lowercase host, no scheme / path / query / port / leading www. '' if none."""
    if not url_or_domain or not isinstance(url_or_domain, str):
        return ""
    s = url_or_domain.strip().lower()
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)  # scheme
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]  # path/query/frag
    s = s.split("@")[-1]  # if an email slipped through
    s = s.split(":", 1)[0]  # port
    if s.startswith("www."):
        s = s[4:]
    return s.strip(". ")


def registrable(domain: str | None) -> str:
    """Reduce a host to its registrable domain (collapses subdomains).

    `mail.dslrpros.com` → `dslrpros.com`; `foo.co.in` → `foo.co.in`. Heuristic
    (no public-suffix list): keep 3 labels when the 2nd-last is a known SLD.
    """
    d = normalize_domain(domain)
    if not d:
        return ""
    parts = d.split(".")
    if len(parts) <= 2:
        return d
    if parts[-2] in _SLD and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def domain_from_email(email: str | None) -> str:
    if not email or not isinstance(email, str) or "@" not in email:
        return ""
    return registrable(email.rsplit("@", 1)[-1])


def norm_name(name: str | None) -> str:
    """Collapse to a comparable company token: lowercase, drop punctuation +
    legal-form suffixes + extra whitespace. 'DSLRPros, LLC.' → 'dslrpros'."""
    if not name or not isinstance(name, str):
        return ""
    s = re.sub(r"[^a-z0-9 ]+", " ", name.strip().lower())
    toks = [t for t in s.split() if t and t not in _LEGAL_SUFFIXES]
    return " ".join(toks).strip()


def make_aliases(name: str | None, extra: list[str] | None = None) -> set[str]:
    """Deterministic alias set for a target company name (+ advisory extras).

    Includes the normalized name, its no-space form, and any Claude-proposed
    extras (each normalized). Used by `verdict` for name-match tolerance.
    """
    out: set[str] = set()
    for n in [name, *(extra or [])]:
        nn = norm_name(n)
        if nn:
            out.add(nn)
            out.add(nn.replace(" ", ""))
    return out


def _name_matches(person_name: str, aliases: set[str]) -> bool:
    """True when a normalized employer name matches any alias (containment both
    ways for names ≥4 chars, so 'dslrpros' ~ 'dslrpros usa')."""
    pn = norm_name(person_name)
    if not pn:
        return False
    pn_ns = pn.replace(" ", "")
    for a in aliases:
        if not a:
            continue
        a_ns = a.replace(" ", "")
        if pn == a or pn_ns == a_ns:
            return True
        if len(a_ns) >= 4 and len(pn_ns) >= 4 and (a_ns in pn_ns or pn_ns in a_ns):
            return True
    return False


def employer_domain(raw: dict) -> str:
    """Best-effort registrable domain of a raw record's CURRENT employer.

    Defensive across actor shapes: explicit company-domain fields, nested
    organization/company objects, a website field, then the work-email domain.
    '' when no employer domain signal is present.
    """
    if not isinstance(raw, dict):
        return ""
    for k in ("company_domain", "organization_domain", "primary_domain",
              "companyDomain", "domain", "17_Query_domain"):
        d = registrable(raw.get(k) if isinstance(raw.get(k), str) else None)
        if d:
            return d
    for k in ("organization", "company", "currentPosition", "current_company"):
        obj = raw.get(k)
        if isinstance(obj, dict):
            for kk in ("primary_domain", "domain", "website_url", "website",
                       "companyWebsite", "url"):
                d = registrable(obj.get(kk) if isinstance(obj.get(kk), str) else None)
                if d:
                    return d
    for k in ("company_website", "organization_website", "website",
              "companyUrl", "company_url"):
        d = registrable(raw.get(k) if isinstance(raw.get(k), str) else None)
        if d:
            return d
    return domain_from_email(
        raw.get("email") or raw.get("email_address") or raw.get("work_email")
    )


def verdict(
    person: dict,
    raw: dict,
    *,
    anchor_domain: str | None,
    target_name: str | None,
    aliases: set[str],
) -> tuple[str, str]:
    """Deterministic membership verdict for one mapped person.

    Returns ("verified"|"mismatch", reason). Religious by design: a POSITIVE
    match (domain OR name/alias) is required — no employer signal → mismatch.
    `person` is the map_person dict; `raw` the original record (for domain).
    """
    anchor = registrable(anchor_domain)
    pdom = registrable(person.get("company_domain")) or employer_domain(raw)
    pname = person.get("company_name") or ""

    if anchor and pdom and pdom == anchor:
        return "verified", f"domain match ({pdom})"
    if _name_matches(pname, aliases):
        return "verified", f"name match ({norm_name(pname)})"
    if not pdom and not norm_name(pname):
        return "mismatch", "no employer signal on record"
    if anchor and pdom and pdom != anchor:
        return "mismatch", f"different domain ({pdom} != {anchor})"
    return "mismatch", f"name not matched ({norm_name(pname) or '∅'})"
