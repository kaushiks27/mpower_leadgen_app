"""Claude competitor classifier — module-local thin Anthropic client (OP #11).

ONE Opus call per competitor → a strict-JSON verdict:
  * band        — is-this-a-TRUE-direct-competitor confidence (Sure/Likely/Unsure/No)
  * reason      — one line
  * confidence  — 0..1 (stored as an exact decimal string)
  * country     — best-guess HQ country (drives the Local/Global split)
  * category    — which mPower product/service category it competes in (constrained
                  to the LIVE catalog category set passed in — never invented)
  * selling_to  — customers it sells to (extracted from site + trade records)

Robustness is the contract (user requirement):
  * output forced to strict JSON; we extract the first {...} block.
  * band MUST be one of the four; anything else → "Unsure" ("unscored"), NEVER
    silently "Sure" (a malformed reply must not look like a confident competitor).
  * category is SNAPPED to the provided canonical list (case-insensitive, then a
    safe substring match); an unrecognised category becomes None, never a guess.
  * confidence parsed via Decimal (exact); junk → "0".
  * selling_to accepts a JSON list or a string; empties become a clear note.
  * a second classifier (`propose_queries`) suggests each round's search terms;
    it returns [] on any failure so discovery falls back to deterministic seeds.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation

import httpx

from app.competitors import config

_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

VALID = ("Sure", "Likely", "Unsure", "No")
_NO_CUSTOMER_NOTE = "No public customer data found (website + trade records checked)."

SYSTEM = """You are a competitor analyst for mPower's drone-battery business. mPower (Magnipower Technology Pvt Ltd) manufactures lithium-ion battery packs for drones — agriculture-spraying, surveillance, survey, delivery, mapping UAVs. A mPower COMPETITOR is another company that MANUFACTURES drone / UAV battery packs (the same product mPower sells) — not a company that builds drones, not one that sells only raw cells, and not one that merely resells others' packs. Judge how confident we can be that ONE company is a TRUE direct competitor — NOT whether it is a good sales lead. Reply with strict JSON only: {"name": "<real company name>", "band": "Sure|Likely|Unsure|No", "reason": "<one line>", "confidence": <0..1>, "country": "<HQ country or empty>", "category": "<one provided mPower category or empty>", "selling_to": ["<customer>", ...]}.

Band rubric (true-competitor confidence) with examples grounded in real market data:

SalesPath Sure — clearly manufactures drone/UAV lithium battery packs.
  GOOD: "Grepow / Tattu" — makes Tattu UAV & agri-drone Li-ion/LiPo packs worldwide -> Sure.
  BAD (NOT Sure): a company that lists drone packs but is really a reseller/trader -> Unsure (a channel, not a maker; do not claim Sure).

SalesPath Likely — a real battery-pack maker where drone packs are one of several markets, or a clear maker with one minor gap.
  GOOD: "Enix Power Solutions" — custom Li-ion pack maker, drones among several markets -> Likely.
  BAD (NOT Likely): an unmistakable drone-battery manufacturer with clear evidence -> that is Sure, do not under-rate a clear maker.

SalesPath Unsure — cannot confirm they MANUFACTURE drone packs (could be a cell-only supplier, a distributor, or a reseller).
  GOOD: "Samsung SDI" — supplies battery CELLS many makers use, not finished drone PACKS -> Unsure.
  BAD (NOT Unsure): an obvious drone OEM or a non-company page -> that is No, not Unsure.

SalesPath No — not a competitor at all.
  GOOD: "Garuda Aerospace" / "DJI" — build DRONES and would BUY batteries -> No (a buyer, not a competitor).
  BAD (NOT No): a real drone-battery maker merely missing some detail -> Unsure/Likely, not No (it is still a competitor).

After the band, fill the other fields from the evidence (never invent):
name: the company's real brand/legal name (e.g. "Grepow", "Herewin Power"). The provided name may be a page/blog title or just a domain — correct it. "" if you genuinely cannot tell.
country: the company's HQ country (e.g. "China", "India", "Germany"); "" if unknown.
category: the SINGLE mPower category (from the list given in the user message) this competitor most competes in; "" if none clearly fits. Use ONLY values from that list, verbatim.
selling_to: real CUSTOMER company names found in the evidence (clients / case studies / "trusted by" / import-export buyers). Names only, no prose. [] if none are stated — do not guess."""

USER_TEMPLATE = (
    "Classify this company as an mPower competitor.\n"
    'company name: "{name}"\n'
    "website domain: {domain}\n"
    "mPower categories to choose from: {categories}\n\n"
    "Evidence (search snippet + the company's own pages + public trade records):\n"
    "{evidence}\n\n"
    'Return strict JSON: {{"name":"<real company name>","band":"Sure|Likely|Unsure|No",'
    '"reason":"<one line>","confidence":<0..1>,"country":"<HQ country or empty>",'
    '"category":"<one provided category or empty>","selling_to":["<customer>", ...]}}'
)


class ClaudeError(RuntimeError):
    pass


def build_user(name: str, domain: str, evidence: str, categories: list[str]) -> str:
    cats = ", ".join(categories) if categories else "(none configured)"
    return USER_TEMPLATE.format(
        name=name,
        domain=domain or "(unknown)",
        categories=cats,
        evidence=(evidence or "")[:4000] or "(no evidence gathered)",
    )


def _snap_category(raw: object, categories: list[str]) -> str | None:
    """Snap a returned category to the canonical mPower list (never invent)."""
    val = str(raw or "").strip()
    if not val or val.lower() in {"general", "multiple", "n/a", "none", "unknown"}:
        return None
    low = val.lower()
    for c in categories:
        if c.lower() == low:
            return c          # exact (case-insensitive)
    for c in categories:      # safe substring either direction
        cl = c.lower()
        if cl in low or low in cl:
            return c
    return None               # unrecognised → blank, not a guess


def _join_customers(raw: object) -> str | None:
    """Accept a JSON list or a string of customer names → clean comma-joined str."""
    names: list[str] = []
    if isinstance(raw, list):
        names = [str(x).strip() for x in raw]
    elif isinstance(raw, str):
        names = [p.strip() for p in re.split(r"[,;\n]", raw)]
    cleaned: list[str] = []
    seen = set()
    for n in names:
        n = n.strip(" \"'·-•").strip()
        if not n or n.lower() in {"none", "n/a", "unknown", "various", "not stated"}:
            continue
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(n)
        if len(cleaned) >= 15:
            break
    return ", ".join(cleaned) if cleaned else None


def parse_classification(text: str, categories: list[str]) -> dict:
    """Robust parse → verdict dict. Never silently 'Sure'; never invent a category."""
    fallback = {
        "name": None,
        "band": "Unsure",
        "reason": "unscored — classifier returned no valid verdict",
        "confidence": "0",
        "country": None,
        "category": None,
        "selling_to": None,
        "selling_to_note": _NO_CUSTOMER_NOTE,
    }
    if not text:
        return fallback
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return fallback
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        return fallback
    if not isinstance(obj, dict):
        return fallback

    band = str(obj.get("band", "")).strip().title()
    if band not in VALID:
        return fallback

    reason = str(obj.get("reason", "")).strip()[:300] or "(no reason given)"
    try:
        conf = str(Decimal(str(obj.get("confidence", ""))))
    except (InvalidOperation, ValueError):
        conf = "0"
    name = str(obj.get("name", "")).strip()[:120] or None
    country = str(obj.get("country", "")).strip()[:120] or None
    category = _snap_category(obj.get("category"), categories)
    selling_to = _join_customers(obj.get("selling_to"))
    note = None if selling_to else _NO_CUSTOMER_NOTE
    return {
        "name": name,
        "band": band,
        "reason": reason,
        "confidence": conf,
        "country": country,
        "category": category,
        "selling_to": selling_to,
        "selling_to_note": note,
    }


async def _call(
    token: str, system: str, user: str, *, max_tokens: int, timeout: float, model: str | None = None
) -> str:
    payload = {
        "model": model or DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    headers = {
        "x-api-key": token,
        "anthropic-version": _API_VERSION,
        "content-type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(_URL, headers=headers, json=payload)
    except httpx.HTTPError as e:
        raise ClaudeError(f"could not reach Anthropic: {e}") from e
    if resp.status_code >= 400:
        raise ClaudeError(f"Anthropic returned {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    for block in body.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    return ""


async def classify_competitor(
    token: str,
    *,
    name: str,
    domain: str,
    evidence: str,
    categories: list[str],
    timeout: float = 45.0,
) -> dict:
    """One Opus call → robust verdict dict (see parse_classification)."""
    text = await _call(
        token, SYSTEM, build_user(name, domain, evidence, categories),
        max_tokens=400, timeout=timeout,
    )
    return parse_classification(text, categories)


# --- category-first pipeline: split extract (cheap) + band (strong) ----------
# The walk-insight flow fills columns BEFORE the verdict: a terse EXTRACTION pass
# (name/country/category/selling-to from the crawl) on a cheap model, then the
# load-bearing BAND on the strong model — over the already-enriched line.

EXTRACT_SYSTEM = """You extract factual fields about a company from web evidence for mPower's drone-battery competitor database. Do NOT judge whether it is a competitor — only extract what the evidence actually states. Reply with strict JSON only: {"name":"<real company name or empty>","country":"<HQ country or empty>","category":"<one provided mPower category or empty>","selling_to":["<customer>", ...]}. Never invent: leave a field "" or [] when the evidence does not state it. name: the company's real brand/legal name (the provided name may be a page/blog title or just a domain — correct it). country: the HQ country (e.g. "China", "India", "Germany"). category: EXACTLY one of the provided mPower categories, verbatim, or "" if none clearly fits. selling_to: real CUSTOMER company names found in the evidence (clients / case studies / "trusted by" / import-export buyers) — names only, [] if none are stated."""

EXTRACT_USER_TEMPLATE = (
    "Extract the fields for this company.\n"
    'company name (may be a page title — correct it): "{name}"\n'
    "website domain: {domain}\n"
    "mPower categories to choose from: {categories}\n\n"
    "Evidence (search snippet + the company's own pages + public trade records):\n"
    "{evidence}\n\n"
    'Return strict JSON: {{"name":"<real name>","country":"<HQ country or empty>",'
    '"category":"<one provided category or empty>","selling_to":["<customer>", ...]}}'
)


def build_extract_user(name: str, domain: str, evidence: str, categories: list[str]) -> str:
    cats = ", ".join(categories) if categories else "(none configured)"
    return EXTRACT_USER_TEMPLATE.format(
        name=name,
        domain=domain or "(unknown)",
        categories=cats,
        evidence=(evidence or "")[:4000] or "(no evidence gathered)",
    )


def parse_profile(text: str, categories: list[str]) -> dict:
    """Robust parse of the EXTRACT pass → {name, country, category, selling_to,
    selling_to_note}. Category snapped to the canonical set (never invented)."""
    fallback = {
        "name": None, "country": None, "category": None,
        "selling_to": None, "selling_to_note": _NO_CUSTOMER_NOTE,
    }
    if not text:
        return fallback
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return fallback
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        return fallback
    if not isinstance(obj, dict):
        return fallback
    name = str(obj.get("name", "")).strip()[:120] or None
    country = str(obj.get("country", "")).strip()[:120] or None
    category = _snap_category(obj.get("category"), categories)
    selling_to = _join_customers(obj.get("selling_to"))
    note = None if selling_to else _NO_CUSTOMER_NOTE
    return {
        "name": name, "country": country, "category": category,
        "selling_to": selling_to, "selling_to_note": note,
    }


async def extract_profile(
    token: str, *, name: str, domain: str, evidence: str, categories: list[str], timeout: float = 40.0
) -> dict:
    """Cheap-model EXTRACT pass (stages 3+4) → name/country/category/selling-to."""
    text = await _call(
        token, EXTRACT_SYSTEM, build_extract_user(name, domain, evidence, categories),
        max_tokens=400, timeout=timeout, model=config.EXTRACT_MODEL,
    )
    return parse_profile(text, categories)


def build_band_user(
    name: str, domain: str, evidence: str, *,
    category: str | None, country: str | None, selling_to: str | None, categories: list[str],
) -> str:
    """Band-stage user prompt — feeds the ALREADY-ENRICHED line to the strong model
    so the verdict sees the filled columns, not just raw evidence."""
    cats = ", ".join(categories) if categories else "(none configured)"
    known = []
    if category:
        known.append(f"category (from the search that found it): {category}")
    if country:
        known.append(f"HQ country: {country}")
    if selling_to:
        known.append(f"sells to: {selling_to}")
    known_block = "\n".join(known) or "(none enriched yet)"
    return (
        "Decide the true-competitor BAND for this company.\n"
        f'company name: "{name}"\n'
        f"website domain: {domain or '(unknown)'}\n"
        f"mPower categories: {cats}\n"
        f"already-enriched facts:\n{known_block}\n\n"
        "Evidence (search snippet + the company's own pages + public trade records):\n"
        f"{(evidence or '')[:4000] or '(no evidence gathered)'}\n\n"
        'Return strict JSON: {"name":"<real name>","band":"Sure|Likely|Unsure|No",'
        '"reason":"<one line>","confidence":<0..1>,"country":"<HQ country or empty>",'
        '"category":"<one provided category or empty>","selling_to":["<customer>", ...]}'
    )


async def classify_band(
    token: str, *, name: str, domain: str, evidence: str,
    category: str | None, country: str | None, selling_to: str | None,
    categories: list[str], timeout: float = 45.0,
) -> dict:
    """Strong-model BAND pass (stage 5) over the enriched line → {name, band,
    reason, confidence}. Reuses the calibrated SYSTEM rubric (good/bad few-shot)."""
    text = await _call(
        token, SYSTEM,
        build_band_user(
            name, domain, evidence,
            category=category, country=country, selling_to=selling_to, categories=categories,
        ),
        max_tokens=400, timeout=timeout, model=DEFAULT_MODEL,
    )
    v = parse_classification(text, categories)
    return {
        "name": v["name"], "band": v["band"],
        "reason": v["reason"], "confidence": v["confidence"],
    }


# --- query proposer (Claude proposes each round's search terms) --------------
PROPOSE_SYSTEM = """You design Google search queries to discover, EXHAUSTIVELY and worldwide, every company that MANUFACTURES drone / UAV lithium battery packs (mPower's competitors). Given mPower's product/service categories and the domains already found, propose the NEXT batch of high-yield search queries that would surface NEW competitor companies not yet found — vary by category, region (China, India, Europe, US, SE-Asia), language hints, synonyms (UAV/drone/agri-spraying/VTOL), and channel (OEM/factory/supplier). Avoid directory/marketplace-only queries. Reply with strict JSON only: {"queries":["...", ...]} (max 16)."""


def build_propose_user(categories: list[str], round_idx: int, seen: list[str]) -> str:
    cats = ", ".join(categories) if categories else "(none)"
    seen_str = ", ".join(seen[:40]) if seen else "(none yet)"
    return (
        f"mPower categories: {cats}\n"
        f"round: {round_idx}\n"
        f"domains already found ({len(seen)}): {seen_str}\n\n"
        'Return strict JSON: {"queries":["...", ...]}'
    )


def parse_queries(text: str) -> list[str]:
    if not text:
        return []
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return []
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        return []
    qs = obj.get("queries") if isinstance(obj, dict) else None
    if not isinstance(qs, list):
        return []
    out: list[str] = []
    for q in qs:
        s = str(q).strip()
        if s:
            out.append(s[:200])
    return out[:16]


async def propose_queries(
    token: str, categories: list[str], round_idx: int, seen: list[str], *, timeout: float = 30.0
) -> list[str]:
    """Claude proposes the round's queries; [] on any failure (→ deterministic seeds)."""
    try:
        text = await _call(
            token, PROPOSE_SYSTEM, build_propose_user(categories, round_idx, seen),
            max_tokens=600, timeout=timeout,
        )
    except ClaudeError:
        return []
    return parse_queries(text)
