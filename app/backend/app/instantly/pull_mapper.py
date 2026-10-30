"""Pure, deterministic Instantly-lead-status → pipeline-action mapping (pull side).

No network, no DB, no float, no LLM. Same input → same output. This is the single
place that decides what an Instantly lead's status MEANS for the app pipeline, so
the meaning is unit-tested in isolation and trivially correctable.

VERIFICATION STATUS (be honest — this gates load-bearing pipeline writes):
- REPLY detection is VERIFIED. Every lead carries `email_reply_count`; `> 0` means
  the prospect replied. Field confirmed live (2026-06-03) against the real workspace.
- SENT/engagement is VERIFIED-ENOUGH. Any of open/click/reply count `> 0` proves the
  lead was actually emailed → at least `emailed`. A zero-engagement lead is NOT
  assumed sent (forward-only honesty), so it stays put.
- BOUNCE / UNSUBSCRIBE encoding is **UNVERIFIED** (see known_issues KI-18). The only
  Instantly campaign in the account is a draft that never sent, so no bounced/unsub
  lead exists to observe. The integer `status` codes below are Instantly's
  best-documented lifecycle values; on an UNKNOWN status we take NO action (never
  mis-suppress a good lead). When a real bounce/unsub appears, confirm the code via
  a live `leads/list` read and correct the two frozensets — nothing else changes.

Bounce/unsub are load-bearing (they auto-suppress = contact-once, irreversible-ish),
so the conservative default is: act only on a code we explicitly list; ignore the rest.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.leads.orm import PIPELINE_STAGES

# --- UNVERIFIED Instantly lead `status` lifecycle codes (KI-18) ---------------
# Observed live: 1 = active. The rest are Instantly's documented lifecycle values,
# pending live confirmation. Keep these tight — an unlisted code = no action.
_BOUNCED_STATUSES = frozenset({-1, -3})  # UNVERIFIED: hard-bounce / blocklisted
_UNSUBSCRIBED_STATUSES = frozenset({3})  # UNVERIFIED: opted out

# Forward-only stage targets this mapper can imply (must exist in PIPELINE_STAGES).
_EMAILED = "emailed"
_REPLIED = "replied"


def _int(value: object) -> int:
    """Coerce an Instantly count/status to int; non-numeric → 0 (defensive)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


@dataclass(frozen=True)
class LeadSignal:
    """What an Instantly lead row tells us — deterministic, derived from raw dict."""

    email: str | None
    status: int | None
    reply_count: int
    engaged: bool  # opened/clicked/replied → proof it was actually sent
    replied: bool
    bounced: bool
    unsubscribed: bool


def classify_lead(raw: dict) -> LeadSignal:
    """Map one raw Instantly lead dict to a deterministic LeadSignal."""
    email = raw.get("email")
    email = email.strip().lower() if isinstance(email, str) and email.strip() else None

    status_raw = raw.get("status")
    status = _int(status_raw) if status_raw is not None else None

    replies = _int(raw.get("email_reply_count"))
    opens = _int(raw.get("email_open_count"))
    clicks = _int(raw.get("email_click_count"))

    return LeadSignal(
        email=email,
        status=status,
        reply_count=replies,
        engaged=(replies > 0 or opens > 0 or clicks > 0),
        replied=replies > 0,
        bounced=status in _BOUNCED_STATUSES,
        unsubscribed=status in _UNSUBSCRIBED_STATUSES,
    )


def forward_stage(current_stage: str, signal: LeadSignal) -> str | None:
    """Return a strictly-forward stage implied by the signal, else None.

    Forward-only (locked Q3): never regress, never overwrite a manually-advanced
    stage with an earlier one. `replied` outranks `emailed`. Returns None when the
    implied stage is not ahead of where the lead already is.
    """
    implied: str | None = None
    if signal.replied:
        implied = _REPLIED
    elif signal.engaged:
        implied = _EMAILED
    if implied is None:
        return None

    try:
        cur = PIPELINE_STAGES.index(current_stage)
    except ValueError:
        cur = -1
    nxt = PIPELINE_STAGES.index(implied)
    return implied if nxt > cur else None
