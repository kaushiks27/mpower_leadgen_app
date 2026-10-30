"""Canonical decision-maker ROLE taxonomy for Generate-Leads.

A user picks one or more role GROUPS; `expand_roles` flattens the selected groups
into the deduped, ordered union of individual job-title variants that the LinkedIn
/ fallback actors search for. Pure + deterministic (no I/O) — same input → same
ordered output, so a re-run searches identically.
"""

from __future__ import annotations

# group label → ordered title variants. Order is load-bearing: it fixes the
# search-term order (deterministic actor input).
ROLE_GROUPS: list[tuple[str, list[str]]] = [
    ("Procurement & Sourcing", [
        "Procurement", "Procurement Manager", "Procurement Lead", "Procurement Head",
        "Procurement Director", "Sourcing", "Sourcing Manager", "Sourcing Lead",
        "Strategic Sourcing Manager", "Purchasing", "Purchasing Manager", "Buyer",
        "Senior Buyer", "Category Manager", "Vendor Manager", "Chief Procurement Officer",
    ]),
    ("Supply Chain & Operations", [
        "Supply Chain Manager", "Supply Chain Head", "Supply Chain Director",
        "Operations Manager", "Operations Head", "Production Manager", "Plant Manager",
        "Manufacturing Manager", "Materials Manager", "Logistics Manager",
        "Chief Operating Officer",
    ]),
    ("Engineering & R&D", [
        "R&D Manager", "R&D Head", "Research and Development Engineer", "Design Engineer",
        "Hardware Engineer", "Electrical Engineer", "Battery Engineer",
        "Power Systems Engineer", "Product Engineer", "Engineering Manager",
        "Engineering Head", "VP Engineering", "Chief Technology Officer",
    ]),
    ("Product & Program", [
        "Product Manager", "Product Head", "Program Manager", "Project Manager",
        "Product Owner",
    ]),
    ("Quality", [
        "Quality Manager", "Quality Assurance Manager", "Quality Head", "QC Manager",
    ]),
    ("Executive & Founder", [
        "Founder", "Co-Founder", "CEO", "Chief Executive Officer", "Managing Director",
        "Director", "President", "Owner", "General Manager", "Business Head",
        "Vice President",
    ]),
]

# Fast lookup: group label → title list.
_BY_GROUP: dict[str, list[str]] = {g: titles for g, titles in ROLE_GROUPS}


def expand_roles(group_names: list[str]) -> list[str]:
    """Deduped, ordered union of title variants for the selected role groups.

    Order follows ROLE_GROUPS declaration order, then within-group order; an
    unknown group name is ignored. Case-insensitive dedup, first-occurrence wins.
    Deterministic: same selection → same list.
    """
    selected = {(g or "").strip() for g in (group_names or [])}
    seen: set[str] = set()
    out: list[str] = []
    for group, titles in ROLE_GROUPS:
        if group not in selected:
            continue
        for t in titles:
            low = t.lower()
            if low not in seen:
                seen.add(low)
                out.append(t)
    return out
