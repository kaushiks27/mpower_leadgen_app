"""Thin async Anthropic Messages client — network I/O isolated for testing.

Calls Claude's Messages API (`POST /v1/messages`) with the icebreaker system +
user prompt and returns the plain text reply. Auth is the `x-api-key` header.
Mirrors the apollo/verify clients: raw httpx (no extra SDK dependency), isolated
behind one function so `email_gen.service` is unit-tested with a fake writer
(no live call, no spend).
"""

from __future__ import annotations

import os

import httpx

_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"

# Default model = Opus 4.8 (icebreaker quality, per the S-7 decision). Overridable
# via env for cost tuning at scale without a code change.
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")


class ClaudeError(RuntimeError):
    """Raised when the Claude call fails (auth, transport, or bad body)."""


def build_payload(system: str, user: str, *, model: str | None = None) -> dict:
    """Pure request body builder (unit-tested directly). Short max_tokens — the
    output is a single sentence, so we cap generation tightly."""
    return {
        "model": model or DEFAULT_MODEL,
        "max_tokens": 120,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }


def extract_text(body: dict) -> str:
    """Pull the first text block out of a Messages response. Defensive."""
    if not isinstance(body, dict):
        return ""
    content = body.get("content")
    if not isinstance(content, list):
        return ""
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            t = block.get("text")
            if isinstance(t, str):
                return t
    return ""


async def write_icebreaker(
    token: str,
    system: str,
    user: str,
    *,
    model: str | None = None,
    timeout: float = 40.0,
) -> str:
    """Call Claude and return the raw text reply. Raises ClaudeError on failure."""
    payload = build_payload(system, user, model=model)
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
        raise ClaudeError(f"Anthropic returned {resp.status_code}: {resp.text[:300]}")
    try:
        body = resp.json()
    except ValueError as e:
        raise ClaudeError("Anthropic returned a non-JSON body") from e
    text = extract_text(body)
    if not text.strip():
        raise ClaudeError("Anthropic returned an empty message")
    return text
