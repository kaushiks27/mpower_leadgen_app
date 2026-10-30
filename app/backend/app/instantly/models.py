"""Pydantic V2 request/response shapes for /api/campaigns/*/instantly-*."""

from __future__ import annotations

from pydantic import BaseModel


class PushRequest(BaseModel):
    """Empty body — the push is fully derived from the campaign (idempotent)."""


class StartRequest(BaseModel):
    """Empty body — Start activates the already-pushed campaign."""


class InstantlyState(BaseModel):
    """The persisted Instantly link for a campaign (or the not-pushed default)."""

    state: str  # not_pushed | draft | live | error
    instantly_campaign_id: str | None = None
    error: str | None = None
    leads_pushed: int = 0
    leads_failed: int = 0
    pushed_at: str | None = None
    started_at: str | None = None


class PushStatus(InstantlyState):
    """Button-state snapshot for the campaign page.

    Counts drive the gate copy. `eligible` = verified-valid + email + icebreaker.
    `pending` = non-archived leads that block "all ready" (not yet valid, or
    valid-with-signal but no icebreaker). `excluded` = valid leads with no scraped
    detail (no icebreaker possible) — counted, shown, but NOT blocking.
    """

    campaign_total: int = 0
    eligible: int = 0
    pending: int = 0
    excluded: int = 0
    can_push: bool = False
    can_start: bool = False
    # gate reason when can_push is False: needs_leads | not_ready | missing_key |
    # already_pushed | None
    reason: str | None = None


# --- Pull side (S-9 — Monitor / Sync) ----------------------------------------


class SyncRequest(BaseModel):
    """Empty body — a Sync is fully derived from the campaign (idempotent)."""


class HotReply(BaseModel):
    """One replied lead, surfaced in the Monitor hot-reply queue."""

    lead_id: int
    name: str
    email: str | None = None
    company: str | None = None
    title: str | None = None
    unibox_url: str  # deep-link into Instantly's Unibox to read/reply the thread


class CampaignMonitor(BaseModel):
    """One pushed campaign's live snapshot for the Monitor sub-tab.

    Counts are DERIVED from the app's own lead stages/flags (which Sync writes), so
    the board and the Monitor never disagree. `last_synced_at` is null until the
    first Sync. `can_sync` is true once a campaign has an Instantly id (draft or live).
    """

    campaign_id: int
    campaign_name: str
    state: str  # not_pushed | draft | live | error
    can_sync: bool
    last_synced_at: str | None = None

    leads_total: int = 0
    emailed: int = 0
    replied: int = 0
    bounced: int = 0
    unsubscribed: int = 0
    unmatched: int = 0  # Instantly leads with no matching app lead (last Sync)

    hot_replies: list[HotReply] = []


class SyncResult(BaseModel):
    """Outcome of one Sync run — what changed + the refreshed snapshot."""

    stage_changes: int = 0
    newly_bounced: int = 0
    newly_unsubscribed: int = 0
    suppressed: int = 0
    leads_pulled: int = 0
    leads_matched: int = 0
    leads_unmatched: int = 0
    monitor: CampaignMonitor
