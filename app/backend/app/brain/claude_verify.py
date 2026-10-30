"""Claude line-by-line data-confidence verifier for catalog rows.

Module-local thin Anthropic client (OP #11 — no import from email_gen). One call
per row → an advisory SalesPath data-confidence band (Sure/Likely/Unsure/No) with
a reason + confidence. The band is recorded + reversible; it never becomes a
load-bearing number. Unparseable replies fall back to Unsure ("unscored"), never
silently Sure.

The SYSTEM prompt (rubric + good/bad few-shot per band) is identical across all
rows — the user-approved prompt. Examples are grounded in real mPower rows.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation

import httpx

_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

VALID = ("Sure", "Likely", "Unsure", "No")

SYSTEM = """You are a data-quality verifier for mPower's product/service catalog. mPower (Magnipower Technology Pvt Ltd) manufactures lithium-ion battery packs for drones — agriculture-spraying, surveillance, survey, delivery, mapping UAVs — plus chargers, custom packs, inverter batteries, and services (custom-pack design, Form D-1 type-certification help, recycling, dealership, bulk orders, R&D). Judge how confident we can be that ONE catalog row is CORRECT and COMPLETE — NOT whether it is a good sales lead. Reply with strict JSON only: {"band": "Sure|Likely|Unsure|No", "reason": "<one line>", "confidence": <0..1>}.

Band rubric (data confidence) with examples grounded in real mPower rows:

SalesPath Sure — complete + plausible + corroborated.
  GOOD: product "mPower 6S 21000mAh Li-ion for Agricultural Spraying", price 45480, category Agriculture Spraying, evidence matches -> Sure.
  BAD (NOT Sure): the same row but price missing -> Unsure (real item, but incomplete data; do not claim Sure).

SalesPath Likely — clearly a real mPower item but one minor gap.
  GOOD: product "44.4V 30Ah Lithium Battery Pack with BMoS", price 92512, category Uncategorized, thin/no evidence -> Likely (has price, but vague category + weak evidence).
  BAD (NOT Likely): clear name + price + matching evidence -> that is Sure, do not under-rate complete rows.

SalesPath Unsure — cannot confirm it is a real, specific catalog item.
  GOOD: product "Battery Pack" (generic), no price, blank category, no evidence -> Unsure.
  BAD (NOT Unsure): obvious junk / non-product -> that is No, not Unsure.

SalesPath No — not a catalog item at all (crawler artifact).
  GOOD: name "Refund/Replacement Policy" or "Your Shopping Cart" captured as a product, no price -> No.
  BAD (NOT No): a real product merely missing its price -> Unsure, not No (item is real, only data is incomplete)."""


class ClaudeError(RuntimeError):
    pass


# Per-row user template (placeholders filled per row). Exposed read-only in the
# dev-reference panel so the prompt shown is always the real one (no drift).
USER_TEMPLATE = (
    "Verify this catalog row.\n"
    "kind: {kind}\n"
    'name: "{name}"\n'
    "price_inr: {price}\n"
    'category: "{category}"\n'
    "source_url: {source_url}\n"
    'evidence (from site crawl): "{evidence}"\n\n'
    'Return JSON: {{"band": "Sure|Likely|Unsure|No", "reason": "<one line>", "confidence": <0..1>}}'
)


def build_user(item, evidence: str) -> str:
    return USER_TEMPLATE.format(
        kind=item.kind,
        name=item.name,
        price=item.price_inr or "(none)",
        category=item.category or "",
        source_url=item.source_url or "",
        evidence=(evidence or "")[:500] or "(no page matched)",
    )


def parse_verdict(text: str) -> dict:
    """Robust parse -> {band, reason, confidence}. Never silently 'Sure'."""
    fallback = {
        "band": "Unsure",
        "reason": "unscored — verifier returned no valid band",
        "confidence": "0",
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
    band = str(obj.get("band", "")).strip().title()
    if band not in VALID:
        return fallback
    reason = str(obj.get("reason", "")).strip()[:300] or "(no reason given)"
    conf = obj.get("confidence", "")
    try:
        conf_str = str(Decimal(str(conf)))
    except (InvalidOperation, ValueError):
        conf_str = "0"
    return {"band": band, "reason": reason, "confidence": conf_str}


async def verify_item(
    token: str, item, evidence: str, *, model: str | None = None, timeout: float = 40.0
) -> dict:
    payload = {
        "model": model or DEFAULT_MODEL,
        "max_tokens": 200,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": build_user(item, evidence)}],
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
    text = ""
    for block in body.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            break
    return parse_verdict(text)
