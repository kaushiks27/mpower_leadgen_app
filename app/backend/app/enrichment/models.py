"""Pydantic V2 shapes for /api/campaigns/{id}/enrich + credit ceilings."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EnrichRequest(BaseModel):
    # Enrich is idempotent: it always processes EVERY not-yet-enriched lead on
    # the campaign (no user-set per-run cap). Body is empty; spend is bounded by
    # the monthly credit ceiling, and already-enriched leads cost 0 credits.
    # (Field kept absent on purpose — extra body keys are ignored.)
    pass


class EnrichStatus(BaseModel):
    """Button-state snapshot for the Apollo-Enrich panel."""

    campaign_total: int  # non-archived leads on this campaign
    un_enriched: int  # leads with no enriched_at (would be processed)
    eligible: int  # leads whose email is verified-deliverable (valid)
    can_enrich: bool
    # Why disabled, so the UI shows the right message:
    #   "nothing_to_enrich" -> every lead already enriched
    #   "missing_apollo_key" / "missing_mv_key" -> key not set
    #   "apollo_ceiling"     -> Apollo monthly ceiling reached
    #   None                 -> enrich allowed
    reason: str | None = None


class CeilingRow(BaseModel):
    provider: str
    monthly_limit: int  # 0 = no ceiling
    used: int
    remaining: int | None  # None = no ceiling
    pct: int  # integer percent used (0 when no ceiling)
    period: str  # "YYYY-MM"


class CeilingUpdate(BaseModel):
    monthly_limit: int = Field(ge=0, le=10_000_000)
