"""Claude "widen" — propose a BROADER Apify search query when results saturate.

When stage-1 LinkedIn discovery for a company stops yielding new people, the
worker PAUSES and asks the user (in-app popup) whether to widen. ONLY on the
user's explicit approval does the worker call `propose_widen_query`: Claude is
shown the exact Apify search query that saturated and is asked to rewrite it, in
the same format, to surface ~50% more of the right decision-makers.

HARD RULE (CLAUDE.md exact-math): Claude NEVER returns leads, a count, or a
pipeline decision — it returns ONLY a rewritten search query (job-title /
keyword strings), which is fed back into the SAME deterministic discovery. The
result is advisory: any parse failure → [] (the search proceeds unwidened).
Module-local thin Anthropic client (OP #11 — no import from brain / email_gen).
"""

from __future__ import annotations

import json
import re

import httpx

from app.leadgen import config

_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"

# Keys an actor-input "query" may carry its job-title list under (defensive —
# different actors name it differently). parse_titles scans all of them.
_TITLE_KEYS = (
    "titles", "currentJobTitles", "contact_job_title",
    "job_titles", "jobTitles", "roles",
)

# --- prompt (role · persona · task · example · format) -----------------------
SYSTEM = (
    "ROLE: You are a senior Apify lead-scraping engineer.\n"
    "PERSONA: You run people-discovery for mPower, a company that sells lithium "
    "battery packs to drone makers and their resellers/distributors. You know how "
    "B2B title-based searches narrow too far and how to broaden them with "
    "synonyms, seniority variants, and adjacent buying-decision roles.\n"
    "TASK: You are given the exact Apify actor search query that JUST STOPPED "
    "returning new people for one company. Rewrite it — same JSON shape, same "
    "field names — so it would realistically surface about 50% MORE of the right "
    "decision-makers (procurement, sourcing, supply-chain, engineering, product, "
    "quality, and leadership who influence battery-pack buying). Broaden the "
    "title list with synonyms and seniority variants; do not invent unrelated "
    "roles and do not remove the company or location constraints.\n"
    "EXAMPLE: given {\"companyName\":\"Acme\",\"currentJobTitles\":[\"Buyer\"],"
    "\"locations\":[\"India\"]} a good rewrite is {\"companyName\":\"Acme\","
    "\"currentJobTitles\":[\"Buyer\",\"Senior Buyer\",\"Purchasing Manager\","
    "\"Procurement Manager\",\"Sourcing Manager\",\"Category Manager\","
    "\"Supply Chain Manager\"],\"locations\":[\"India\"]}.\n"
    "FORMAT: Reply with the rewritten query as STRICT JSON ONLY — the same object "
    "shape you were given, no prose, no markdown, no commentary."
)

USER_TEMPLATE = (
    "This Apify search query stopped yielding new results for the target company:\n"
    "{earlier_query}\n\n"
    "Rewrite it per your instructions so it returns ~50% more decision-makers. "
    "Return only the new query as JSON in the same format."
)


def parse_titles(text: str) -> list[str]:
    """Robust parse of a model reply → deduped, ordered list of title strings.

    Accepts either {"titles":[...]} or a full rewritten actor-input object whose
    job titles live under any of `_TITLE_KEYS`. [] on any failure (advisory).
    """
    if not text:
        return []
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return []
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        return []
    if not isinstance(obj, dict):
        return []
    raw: list = []
    for key in _TITLE_KEYS:
        val = obj.get(key)
        if isinstance(val, list):
            raw.extend(val)
    seen: set[str] = set()
    out: list[str] = []
    for t in raw:
        if isinstance(t, str) and t.strip():
            v = t.strip()
            low = v.lower()
            if low not in seen:
                seen.add(low)
                out.append(v)
    return out


# --- advisory company-name aliases (membership-gate tolerance) ---------------
ALIAS_SYSTEM = (
    "ROLE: You are a B2B company-name disambiguation assistant.\n"
    "TASK: Given a company name, return its common ALTERNATIVE NAME SPELLINGS — "
    "legal-form variants, abbreviations, the 'doing-business-as' name, and obvious "
    "spacing variants (e.g. 'DSLRPros' ⇄ 'DSLR Pros'). Do NOT invent unrelated "
    "companies, parent/holding names, or guesses; if unsure, return fewer.\n"
    "FORMAT: Reply with STRICT JSON ONLY — a flat array of strings, e.g. "
    "[\"DSLR Pros\",\"DSLRPros LLC\"]. No prose, no markdown."
)


def parse_aliases(text: str) -> list[str]:
    """Parse a model reply → deduped list of alias strings ([] on any failure)."""
    if not text:
        return []
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except (ValueError, TypeError):
        return []
    if not isinstance(arr, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for a in arr:
        if isinstance(a, str) and a.strip():
            low = a.strip().lower()
            if low not in seen:
                seen.add(low)
                out.append(a.strip())
    return out


async def propose_aliases(
    token: str, company_name: str, *, model: str | None = None, timeout: float = 30.0
) -> list[str]:
    """Advisory: ask Claude for alternative spellings of `company_name`.

    Output ONLY seeds the deterministic membership gate's alias set — Claude never
    decides whether a lead is kept. [] on any error/parse failure (gate then uses
    the deterministic name-derived aliases only).
    """
    name = (company_name or "").strip()
    if not name:
        return []
    payload = {
        "model": model or config.WIDEN_MODEL,
        "max_tokens": 200,
        "system": ALIAS_SYSTEM,
        "messages": [{"role": "user", "content": f"Company name: {name}"}],
    }
    headers = {
        "x-api-key": token,
        "anthropic-version": _API_VERSION,
        "content-type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(_URL, headers=headers, json=payload)
    except httpx.HTTPError:
        return []
    if resp.status_code >= 400:
        return []
    try:
        body = resp.json()
    except ValueError:
        return []
    text = ""
    for block in body.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            break
    return parse_aliases(text)


async def propose_widen_query(
    token: str,
    earlier_input: dict,
    *,
    model: str | None = None,
    timeout: float = 40.0,
) -> list[str]:
    """Show Claude the saturated query; get a widened query → new title list.

    Advisory only: returns the broadened job-title list parsed from Claude's
    rewritten query, or [] on any error/parse failure.
    """
    try:
        earlier_query = json.dumps(earlier_input, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        earlier_query = str(earlier_input)
    user = USER_TEMPLATE.format(earlier_query=earlier_query)
    payload = {
        "model": model or config.WIDEN_MODEL,
        "max_tokens": 400,
        "system": SYSTEM,
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
    except httpx.HTTPError:
        return []
    if resp.status_code >= 400:
        return []
    try:
        body = resp.json()
    except ValueError:
        return []
    text = ""
    for block in body.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            break
    return parse_titles(text)
