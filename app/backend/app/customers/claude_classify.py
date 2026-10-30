"""Claude customer classifier — module-local thin Anthropic client (OP #11).

ONE Opus call per company → a strict-JSON verdict:
  * band        — is-this-a-genuine-CUSTOMER confidence (Sure/Likely/Unsure/No)
  * reason      — one line
  * confidence  — 0..1 (stored as an exact decimal string)
  * country     — best-guess HQ country (drives the Local/Global split)
  * category    — which mPower product/service category fits (constrained to the
                  LIVE catalog category set passed in — never invented)
  * ctype       — OEM | Reseller | Distributor (or "" when unclear — never a guess)

A CUSTOMER is a company mPower would SELL drone batteries TO:
  * OEM        — a drone MANUFACTURER (builds drones, buys packs). NOT a battery maker.
  * Reseller / Distributor — of drone batteries / mPower's product categories.
A company that MANUFACTURES drone batteries is a COMPETITOR, not a customer → band "No".

Robustness is the contract:
  * output forced to strict JSON; we extract the first {...} block.
  * band MUST be one of the four; anything else → "Unsure", NEVER silently "Sure".
  * category + ctype are SNAPPED to the canonical sets; unrecognised → None, never a guess.
  * confidence parsed via Decimal (exact); junk → "0".
  * a second classifier (`propose_queries`) suggests each round's search terms; [] on failure.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation

import httpx

from app.customers import config

_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

VALID = ("Sure", "Likely", "Unsure", "No")

SYSTEM = """You are a sales-prospecting analyst for mPower's drone-battery business. mPower (Magnipower Technology Pvt Ltd) MANUFACTURES lithium-ion battery packs for drones — agriculture-spraying, surveillance, survey, delivery, mapping UAVs. A mPower CUSTOMER is a company mPower would SELL those packs TO. There are exactly two kinds: (1) an OEM — a company that MANUFACTURES drones / UAVs and therefore BUYS battery packs; and (2) a Reseller or Distributor of drone batteries / drone parts. A company that MANUFACTURES drone battery packs itself is a COMPETITOR, NOT a customer. A company that sells only raw battery CELLS is not a customer either. Judge how confident we can be that ONE company is a GENUINE prospective customer — and which TYPE it is. Reply with strict JSON only: {"name": "<real company name>", "band": "Sure|Likely|Unsure|No", "reason": "<one line>", "confidence": <0..1>, "country": "<HQ country or empty>", "category": "<one provided mPower category or empty>", "ctype": "OEM|Reseller|Distributor or empty"}.

Band rubric (genuine-customer confidence) with examples grounded in real market data:

SalesPath Sure — clearly a drone OEM (builds drones) OR a bona-fide drone-battery reseller/distributor.
  GOOD: "Garuda Aerospace" / "ideaForge" — build agriculture & surveillance DRONES, would buy packs -> Sure, ctype OEM.
  GOOD: a named authorized distributor stocking multiple drone-battery brands -> Sure, ctype Distributor.
  BAD (NOT Sure): "Grepow / Tattu" — they MANUFACTURE drone battery packs -> that is a competitor -> No, never Sure.

SalesPath Likely — probably a customer with a small gap (drone maker where drones are one of several lines, or a reseller whose drone-battery focus is partial).
  GOOD: an industrial-automation firm with a growing UAV product line -> Likely, ctype OEM.
  BAD (NOT Likely): an unmistakable drone manufacturer with clear evidence -> that is Sure, do not under-rate a clear buyer.

SalesPath Unsure — cannot confirm they BUILD drones or RESELL drone batteries (could be a services/mapping firm, a hobby shop, or unclear).
  GOOD: a drone-services / aerial-survey operator that flies drones but may not buy packs at scale -> Unsure.
  BAD (NOT Unsure): an obvious battery MANUFACTURER -> that is No (a competitor), not Unsure.

SalesPath No — not a customer at all.
  GOOD: "Grepow", "Amperex", "Samsung SDI" — make battery packs or cells -> No (competitor / supplier, not a buyer).
  GOOD: a marketplace listing or a market-research page -> No.
  BAD (NOT No): a real drone OEM merely missing some detail -> Unsure/Likely, not No (it is still a prospective buyer).

After the band, fill the other fields from the evidence (never invent):
name: the company's real brand/legal name. The provided name may be a page title or just a domain — correct it. "" if you genuinely cannot tell.
country: the company's HQ country (e.g. "India", "United States", "China"); "" if unknown.
category: the SINGLE mPower category (from the list given in the user message) this customer best fits; "" if none clearly fits. Use ONLY values from that list, verbatim.
ctype: "OEM" if the company BUILDS drones; "Reseller" or "Distributor" if it resells/distributes drone batteries/parts; "" if you cannot tell (do NOT guess between Reseller and Distributor — leave "" if unclear). NEVER label a battery MANUFACTURER as a customer type."""

USER_TEMPLATE = (
    "Classify this company as an mPower customer.\n"
    'company name: "{name}"\n'
    "website domain: {domain}\n"
    "mPower categories to choose from: {categories}\n\n"
    "Evidence (search snippet + the company's own pages):\n"
    "{evidence}\n\n"
    'Return strict JSON: {{"name":"<real company name>","band":"Sure|Likely|Unsure|No",'
    '"reason":"<one line>","confidence":<0..1>,"country":"<HQ country or empty>",'
    '"category":"<one provided category or empty>","ctype":"OEM|Reseller|Distributor or empty"}}'
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


def _snap_ctype(raw: object) -> str | None:
    """Snap a returned type to OEM | Reseller | Distributor (never a guess)."""
    val = str(raw or "").strip().lower()
    if not val or val in {"none", "n/a", "unknown", "unclear", "both", "other"}:
        return None
    # A battery maker is never a customer type — refuse it outright.
    if "battery" in val and "manufactur" in val:
        return None
    if "distribut" in val:
        return "Distributor"
    if "resell" in val or "dealer" in val or "retail" in val:
        return "Reseller"
    if "oem" in val or "manufactur" in val or "maker" in val or "builder" in val:
        return "OEM"
    return None


def parse_classification(text: str, categories: list[str]) -> dict:
    """Robust parse → verdict dict. Never silently 'Sure'; never invent a category/type."""
    fallback = {
        "name": None,
        "band": "Unsure",
        "reason": "unscored — classifier returned no valid verdict",
        "confidence": "0",
        "country": None,
        "category": None,
        "ctype": None,
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
    ctype = _snap_ctype(obj.get("ctype"))
    return {
        "name": name,
        "band": band,
        "reason": reason,
        "confidence": conf,
        "country": country,
        "category": category,
        "ctype": ctype,
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


# --- category-first pipeline: split extract (cheap) + band (strong) ----------
# The flow fills columns BEFORE the verdict: a terse EXTRACTION pass
# (name/country/category/ctype from the crawl) on a cheap model, then the
# load-bearing BAND on the strong model — over the already-enriched line.

EXTRACT_SYSTEM = """You extract factual fields about a company from web evidence for mPower's drone-customer database. Do NOT judge whether it is a customer — only extract what the evidence actually states. Reply with strict JSON only: {"name":"<real company name or empty>","country":"<HQ country or empty>","category":"<one provided mPower category or empty>","ctype":"OEM|Reseller|Distributor or empty"}. Never invent: leave a field "" when the evidence does not state it. name: the company's real brand/legal name (the provided name may be a page title or just a domain — correct it). country: the HQ country (e.g. "India", "China", "Germany"). category: EXACTLY one of the provided mPower categories, verbatim, or "" if none clearly fits. ctype: "OEM" if the company MANUFACTURES drones/UAVs; "Distributor" or "Reseller" if it distributes/resells drone batteries or parts; "" if unclear OR if the company manufactures BATTERIES itself (a battery maker is not a customer type)."""

EXTRACT_USER_TEMPLATE = (
    "Extract the fields for this company.\n"
    'company name (may be a page title — correct it): "{name}"\n'
    "website domain: {domain}\n"
    "mPower categories to choose from: {categories}\n\n"
    "Evidence (search snippet + the company's own pages):\n"
    "{evidence}\n\n"
    'Return strict JSON: {{"name":"<real name>","country":"<HQ country or empty>",'
    '"category":"<one provided category or empty>","ctype":"OEM|Reseller|Distributor or empty"}}'
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
    """Robust parse of the EXTRACT pass → {name, country, category, ctype}.
    Category + ctype snapped to canonical sets (never invented)."""
    fallback = {"name": None, "country": None, "category": None, "ctype": None}
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
    ctype = _snap_ctype(obj.get("ctype"))
    return {"name": name, "country": country, "category": category, "ctype": ctype}


async def extract_profile(
    token: str, *, name: str, domain: str, evidence: str, categories: list[str], timeout: float = 40.0
) -> dict:
    """Cheap-model EXTRACT pass (stages 3+4) → name/country/category/ctype."""
    text = await _call(
        token, EXTRACT_SYSTEM, build_extract_user(name, domain, evidence, categories),
        max_tokens=400, timeout=timeout, model=config.EXTRACT_MODEL,
    )
    return parse_profile(text, categories)


def build_band_user(
    name: str, domain: str, evidence: str, *,
    category: str | None, country: str | None, ctype: str | None, categories: list[str],
) -> str:
    """Band-stage user prompt — feeds the ALREADY-ENRICHED line to the strong model
    so the verdict sees the filled columns, not just raw evidence."""
    cats = ", ".join(categories) if categories else "(none configured)"
    known = []
    if category:
        known.append(f"category (from the search that found it): {category}")
    if country:
        known.append(f"HQ country: {country}")
    if ctype:
        known.append(f"likely type: {ctype}")
    known_block = "\n".join(known) or "(none enriched yet)"
    return (
        "Decide the genuine-customer BAND for this company.\n"
        f'company name: "{name}"\n'
        f"website domain: {domain or '(unknown)'}\n"
        f"mPower categories: {cats}\n"
        f"already-enriched facts:\n{known_block}\n\n"
        "Evidence (search snippet + the company's own pages):\n"
        f"{(evidence or '')[:4000] or '(no evidence gathered)'}\n\n"
        'Return strict JSON: {"name":"<real name>","band":"Sure|Likely|Unsure|No",'
        '"reason":"<one line>","confidence":<0..1>,"country":"<HQ country or empty>",'
        '"category":"<one provided category or empty>","ctype":"OEM|Reseller|Distributor or empty"}'
    )


async def classify_band(
    token: str, *, name: str, domain: str, evidence: str,
    category: str | None, country: str | None, ctype: str | None,
    categories: list[str], timeout: float = 45.0,
) -> dict:
    """Strong-model BAND pass (stage 5) over the enriched line → {name, band,
    reason, confidence, ctype}. Reuses the calibrated SYSTEM rubric (good/bad few-shot)."""
    text = await _call(
        token, SYSTEM,
        build_band_user(
            name, domain, evidence,
            category=category, country=country, ctype=ctype, categories=categories,
        ),
        max_tokens=400, timeout=timeout, model=DEFAULT_MODEL,
    )
    v = parse_classification(text, categories)
    return {
        "name": v["name"], "band": v["band"],
        "reason": v["reason"], "confidence": v["confidence"], "ctype": v["ctype"],
    }


# --- query proposer (Claude proposes each round's search terms) --------------
PROPOSE_SYSTEM = """You design Google search queries to discover, EXHAUSTIVELY and worldwide, every company that would BUY drone battery packs from mPower. Two kinds of target: (1) OEMs — companies that MANUFACTURE drones / UAVs (agriculture-spraying, surveillance, survey, delivery, mapping); (2) Resellers / Distributors of drone batteries and drone parts. Do NOT target companies that manufacture batteries themselves (those are competitors). Given mPower's product/service categories and the domains already found, propose the NEXT batch of high-yield queries that surface NEW customer companies not yet found — vary by category, region (India, US, Europe, China, SE-Asia), drone segment, and channel (OEM vs distributor). Avoid directory/marketplace-only queries. Reply with strict JSON only: {"queries":["...", ...]} (max 16)."""


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
