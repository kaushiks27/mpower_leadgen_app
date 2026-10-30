"""Pydantic V2 request/response shapes for /api/campaigns/{id}/icebreaker*."""

from __future__ import annotations

from pydantic import BaseModel


class IcebreakerRequest(BaseModel):
    # Empty body — generation is idempotent (only leads missing an icebreaker
    # are written). No per-run cap; every eligible lead is processed.
    pass


class LeadIcebreakerRequest(BaseModel):
    # 08062026_cr CR-2: master Leads-page bulk action — the selected lead ids.
    # Only send-eligible (verified) leads without an icebreaker are written.
    lead_ids: list[int] = []


class IcebreakerStatus(BaseModel):
    campaign_total: int  # non-archived leads on the campaign
    missing: int  # leads with NO icebreaker yet (would be generated)
    no_source: int  # leads with no scraped signal (skipped, can't write one)
    written: int  # leads that already have an icebreaker
    can_generate: bool
    reason: str | None = None  # nothing_to_write | missing_key
