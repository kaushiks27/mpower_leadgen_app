"""Icebreaker prompt construction + output sanitization (pure, no I/O).

Kept separate from the network client so the prompt + the "is this human?"
cleanup are unit-tested directly. The voice mirrors the MAXA cold-email examples
(`references/email_examples/`): casual, lower-key, specific, no sales gloss. The
banned-word list is the AI-vocabulary tell-list from
`references/antiAI_writing/ANTI AI WRITING STYLE.md`.
"""

from __future__ import annotations

import json

# AI-vocabulary tells (subset of the anti-AI doc's "words to watch") + the cold-
# outreach clichés the lessons doc warns against. If the model emits one, we flag
# the line low-quality (caller can keep it but it counts as a soft failure).
BANNED_WORDS = (
    "delve",
    "tapestry",
    "testament",
    "showcase",
    "underscore",
    "pivotal",
    "intricate",
    "intricacies",
    "vibrant",
    "robust",
    "leverage",
    "leveraging",
    "fostering",
    "garner",
    "elevate",
    "seamless",
    "landscape",
    "realm",
    "navigating",
    "spearhead",
    "synergy",
    "resonate",
    "in today's",
    "ever-evolving",
    "fast-paced",
    "i hope this email finds you well",
    "i came across",
    "i couldn't help but notice",
    "i noticed your impressive",
    "your impressive",
    "i was impressed",
    "reaching out because",
)

# The most useful signal fields we try to read out of the scraped JSON record.
_SIGNAL_KEYS = (
    "headline",
    "summary",
    "bio",
    "about",
    "description",
    "apollo_headline",
    "occupation",
    "current_role",
    "tagline",
)


def extract_context(lead_fields: dict, scrape_raw: str | None) -> dict:
    """Build a compact, real context dict for one lead. Never fabricates.

    `lead_fields` carries the lead's own columns (name/title/company/location);
    `scrape_raw` is the JSON blob stored at scrape time. We pull a short list of
    likely-useful signal strings out of it. Returns {} signals when nothing real
    is present — the caller then SKIPS the lead (no made-up icebreaker).
    """
    ctx: dict = {
        "first_name": (lead_fields.get("first_name") or "").strip(),
        "title": (lead_fields.get("title") or "").strip(),
        "company": (lead_fields.get("company") or "").strip(),
        "location": (lead_fields.get("location") or "").strip(),
        "signals": [],
    }
    raw = _parse_raw(scrape_raw)
    for key in _SIGNAL_KEYS:
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            ctx["signals"].append(val.strip())
    return ctx


def has_signal(ctx: dict) -> bool:
    """True when there is enough real material to write a grounded line.

    A bare name is not enough — we require a title, a company, or a scraped
    signal. No signal => skip (decision: never fabricate).
    """
    return bool(ctx.get("signals") or ctx.get("title") or ctx.get("company"))


def _parse_raw(scrape_raw: str | None) -> dict:
    if not scrape_raw:
        return {}
    try:
        data = json.loads(scrape_raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


SYSTEM_PROMPT = (
    "You write the single opening line of a cold sales email for a B2B drone "
    "company. This line is the personalized icebreaker that sits above a fixed "
    "template, so it must sound like one real person typing to another.\n\n"
    "Hard rules:\n"
    "- Output EXACTLY one sentence, 8 to 24 words. No greeting, no sign-off, no "
    "line breaks, no quotation marks around it.\n"
    "- Reference something concrete and true from the person's details below. "
    "Never invent facts, numbers, mutual connections, or events.\n"
    "- Plain, casual, lower-key. Write like a busy founder, not a marketer.\n"
    "- No em dashes. No semicolons. Use commas.\n"
    "- Do NOT use these openers or anything like them: 'I came across', "
    "'I noticed your impressive', 'I hope this finds you well', 'I couldn't help "
    "but notice', 'reaching out because'.\n"
    "- Banned words: delve, tapestry, robust, leverage, seamless, vibrant, "
    "showcase, landscape, realm, synergy, elevate, pivotal, intricate.\n"
    "- No flattery, no hype, no exclamation marks.\n"
    "- If the only detail is a role + company, write a plain, specific line about "
    "that work. Do not pad it with adjectives.\n\n"
    "Return only the sentence, nothing else."
)


def build_user_prompt(ctx: dict) -> str:
    """Render the per-lead context into the user message."""
    lines = []
    if ctx.get("first_name"):
        lines.append(f"First name: {ctx['first_name']}")
    if ctx.get("title"):
        lines.append(f"Title: {ctx['title']}")
    if ctx.get("company"):
        lines.append(f"Company: {ctx['company']}")
    if ctx.get("location"):
        lines.append(f"Location: {ctx['location']}")
    for i, sig in enumerate(ctx.get("signals", [])[:4], 1):
        # Clip each signal so one giant bio can't blow up the prompt.
        lines.append(f"Profile detail {i}: {sig[:400]}")
    body = "\n".join(lines) if lines else "(no details)"
    return (
        "Write the one-line icebreaker for this person.\n\n"
        f"{body}\n\n"
        "Remember: one sentence, 8-24 words, specific, plain, no em dashes."
    )


def sanitize(raw: str) -> str:
    """Clean the model's reply into a single human line.

    Strips wrapping quotes, collapses whitespace to one line, swaps em/en dashes
    for commas (an AI tell), and trims a trailing label if the model echoed one.
    Pure + deterministic.
    """
    text = (raw or "").strip()
    # Drop a leading label like "Icebreaker:" if the model added one.
    for label in ("icebreaker:", "opening line:", "line:"):
        if text.lower().startswith(label):
            text = text[len(label):].strip()
    # Strip a single layer of wrapping quotes (straight or curly).
    if len(text) >= 2 and text[0] in "\"'“‘" and text[-1] in "\"'”’":
        text = text[1:-1].strip()
    # Collapse any internal newlines/tabs/multispace into single spaces.
    text = " ".join(text.split())
    # Em/en dash -> comma (AI tell). Keep hyphenated words intact.
    text = text.replace(" — ", ", ").replace("—", ", ")
    text = text.replace(" – ", ", ").replace("–", ", ")
    return text.strip()


def looks_human(text: str) -> bool:
    """Soft quality gate: non-empty, single line, no banned tell-words."""
    if not text or "\n" in text:
        return False
    low = text.lower()
    return not any(w in low for w in BANNED_WORDS)
