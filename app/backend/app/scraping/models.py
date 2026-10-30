"""Pydantic V2 request/response shapes for /api/campaigns/{id}/generate-leads."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    # Per-run cap. Default 5 (the first live-test cap). Hard-bounded so a stray
    # value can never trigger a huge paid run.
    cap: int = Field(default=5, ge=1, le=100)
    active_90d: bool = True  # inert for the Apollo actor (KI-7); kept for later


class GenerateResult(BaseModel):
    """Outcome of one Generate-Leads run — all integer counts, deterministic."""

    requested: int  # leads asked of Apify this run (= effective cap)
    fetched: int  # raw records Apify returned
    created: int  # new deduped leads written + tagged to this campaign
    skipped_duplicates: int  # already in the central table (contact-once)
    skipped_no_identity: int  # no LinkedIn/email/name+company -> not dedupable
    campaign_total: int  # campaign's non-archived lead count AFTER this run
    target: int  # campaign target_lead_count (0 = no target)
    remaining: int  # max(0, target - campaign_total); 0 when no target
    can_generate: bool  # target == 0 or campaign_total < target
    message: str


class GenerateStatus(BaseModel):
    """Button-state snapshot for the Generate-Leads panel."""

    campaign_total: int
    target: int
    remaining: int
    can_generate: bool
    # Why the button is disabled, so the UI can show the right message:
    #   "target_met"        -> target lead count reached (grey out)
    #   "no_company_signal" -> no ICP filter selected+saved (S-5c guard)
    #   None                -> generate is allowed
    reason: str | None = None
