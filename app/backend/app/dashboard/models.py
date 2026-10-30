"""Pydantic V2 response shapes for the dashboard summary (read-only).

Counts are exact integers; rates are floats rounded server-side from Decimal
(display-only — never stored, never a pipeline decision).
"""

from __future__ import annotations

from pydantic import BaseModel


class CampaignFunnel(BaseModel):
    """Per-campaign (or All-campaigns total) funnel row."""

    campaign_id: int | None  # None = the synthetic "All campaigns" total row
    campaign_name: str
    # Stage counts, keyed by PIPELINE_STAGES (new..won). Always all stages present.
    stages: dict[str, int]
    # Flag counts (bounced / unsubscribed / not_interested).
    flags: dict[str, int]
    total: int  # non-archived leads in this campaign
    contacted: int  # emailed-or-beyond (rate denominator)
    replied: int  # replied-or-beyond
    positive: int  # replied-or-beyond minus not_interested
    reply_rate: float  # replied/contacted, 1-dp, 0.0 when contacted=0
    positive_rate: float  # positive/contacted, 1-dp


class GoalProgress(BaseModel):
    """5,000-leads/month goal — leads pushed to Instantly this calendar month."""

    pushed_this_month: int
    goal: int
    pct: int  # 0..100 (capped), pushed/goal
    period: str  # "YYYY-MM" (UTC)


class CreditBurnItem(BaseModel):
    """One provider's credit consumption vs ceiling this period."""

    provider: str  # apollo | millionverifier
    used: int
    limit: int  # 0 = unlimited
    pct: int  # 0 when unlimited
    unlimited: bool


class HotReplyItem(BaseModel):
    """A lead sitting at the Replied stage that needs a human (top-of-dashboard)."""

    lead_id: int
    name: str
    company: str | None
    title: str | None
    campaign_name: str | None
    value_inr: int | None
    unibox_url: str
    lead_url: str  # in-app deep link to lead detail


class DashboardSummary(BaseModel):
    active_campaigns: int
    overall_reply_rate: float
    overall_positive_rate: float
    funnels: list[CampaignFunnel]  # per-campaign rows + a trailing "All campaigns" total
    goal: GoalProgress
    credit_burn: list[CreditBurnItem]
    hot_replies: list[HotReplyItem]
