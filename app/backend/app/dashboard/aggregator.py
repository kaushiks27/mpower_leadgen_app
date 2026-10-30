"""Deterministic dashboard aggregation over persisted tables (no writes).

All counts are exact integers; rates use `decimal.Decimal` with ROUND_HALF_UP
(display-only, 1 decimal place). Ordering is deterministic everywhere. No live
external calls, no LLM-computed numbers — every value is a query result.

One-way reads only: leads / campaigns / enrichment ORMs. This module is never
imported by those feature modules (OP #11 boundary).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.orm import Campaign
from app.dashboard.models import (
    CampaignFunnel,
    CreditBurnItem,
    DashboardSummary,
    GoalProgress,
    HotReplyItem,
)
from app.enrichment.credits import current_period, get_ceiling, get_usage, usage_pct
from app.leads.orm import LEAD_FLAGS, PIPELINE_STAGES, Company, Lead, LeadEvent

# Stage classification (cumulative — a "won" lead passed through every prior).
_CONTACTED_STAGES = frozenset({"emailed", "replied", "interested", "won"})
_REPLIED_STAGES = frozenset({"replied", "interested", "won"})

GOAL_TARGET = 5000  # leads/month (locked Q18)
_BURN_PROVIDERS = ("apollo", "millionverifier")
_UNIBOX_URL = "https://app.instantly.ai/app/unibox"


def _rate(numerator: int, denominator: int) -> float:
    """Percent rate, exact Decimal, ROUND_HALF_UP to 1 dp; 0.0 when no denom."""
    if denominator <= 0:
        return 0.0
    pct = (Decimal(numerator) / Decimal(denominator) * Decimal(100)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return float(pct)


def _month_start_utc(now: datetime | None = None) -> datetime:
    """First instant of the current UTC month, naive (matches func.now() storage)."""
    n = now or datetime.now(timezone.utc)
    return datetime(n.year, n.month, 1)


def _empty_stage_counts() -> dict[str, int]:
    return {s: 0 for s in PIPELINE_STAGES}


def _empty_flag_counts() -> dict[str, int]:
    return {f: 0 for f in LEAD_FLAGS}


def _funnel_from_counts(
    campaign_id: int | None,
    campaign_name: str,
    stages: dict[str, int],
    flags: dict[str, int],
) -> CampaignFunnel:
    total = sum(stages.values())
    contacted = sum(stages[s] for s in _CONTACTED_STAGES)
    replied = sum(stages[s] for s in _REPLIED_STAGES)
    # positive = replied-or-beyond minus those explicitly flagged not_interested.
    positive = max(0, replied - flags.get("not_interested", 0))
    return CampaignFunnel(
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        stages=stages,
        flags=flags,
        total=total,
        contacted=contacted,
        replied=replied,
        positive=positive,
        reply_rate=_rate(replied, contacted),
        positive_rate=_rate(positive, contacted),
    )


async def build_summary(db: AsyncSession) -> DashboardSummary:
    # --- Campaign names (resolve ids → labels; deterministic id order) ---
    camp_rows = (
        await db.execute(select(Campaign.id, Campaign.name, Campaign.status, Campaign.archived))
    ).all()
    names: dict[int, str] = {r.id: r.name for r in camp_rows}
    active_campaigns = sum(
        1 for r in camp_rows if r.status == "active" and not r.archived
    )

    # --- Per-campaign funnel from non-archived leads ---
    lead_rows = (
        await db.execute(
            select(
                Lead.campaign_id,
                Lead.stage,
                Lead.bounced,
                Lead.unsubscribed,
                Lead.not_interested,
            ).where(Lead.archived.is_(False))
        )
    ).all()

    # Accumulate per campaign_id (None bucket = unassigned).
    stage_acc: dict[int | None, dict[str, int]] = {}
    flag_acc: dict[int | None, dict[str, int]] = {}
    for row in lead_rows:
        cid = row.campaign_id
        s = stage_acc.setdefault(cid, _empty_stage_counts())
        f = flag_acc.setdefault(cid, _empty_flag_counts())
        if row.stage in s:
            s[row.stage] += 1
        if row.bounced:
            f["bounced"] += 1
        if row.unsubscribed:
            f["unsubscribed"] += 1
        if row.not_interested:
            f["not_interested"] += 1

    funnels: list[CampaignFunnel] = []
    # Deterministic order: real campaigns by id asc, then the unassigned bucket.
    ordered_ids = sorted(
        (cid for cid in stage_acc if cid is not None)
    )
    if None in stage_acc:
        ordered_ids.append(None)  # type: ignore[arg-type]
    for cid in ordered_ids:
        label = (
            names.get(cid, f"Campaign #{cid}") if cid is not None else "Unassigned"
        )
        funnels.append(_funnel_from_counts(cid, label, stage_acc[cid], flag_acc[cid]))

    # --- All-campaigns total row ---
    total_stages = _empty_stage_counts()
    total_flags = _empty_flag_counts()
    for s in stage_acc.values():
        for k, v in s.items():
            total_stages[k] += v
    for f in flag_acc.values():
        for k, v in f.items():
            total_flags[k] += v
    total_row = _funnel_from_counts(None, "All campaigns", total_stages, total_flags)
    funnels.append(total_row)

    # --- 5k goal: distinct leads with a queued audit event this month ---
    month_start = _month_start_utc()
    pushed = (
        await db.execute(
            select(func.count(func.distinct(LeadEvent.lead_id))).where(
                LeadEvent.to_value == "queued",
                LeadEvent.created_at >= month_start,
            )
        )
    ).scalar() or 0
    period = current_period()
    goal = GoalProgress(
        pushed_this_month=int(pushed),
        goal=GOAL_TARGET,
        pct=min(100, (int(pushed) * 100) // GOAL_TARGET) if GOAL_TARGET else 0,
        period=period,
    )

    # --- Credit burn (Apollo + MillionVerifier) vs ceiling, this period ---
    credit_burn: list[CreditBurnItem] = []
    for provider in _BURN_PROVIDERS:
        used = await get_usage(db, provider, period)
        limit = await get_ceiling(db, provider)
        credit_burn.append(
            CreditBurnItem(
                provider=provider,
                used=int(used),
                limit=int(limit),
                pct=usage_pct(used, limit),
                unlimited=(limit == 0),
            )
        )

    # --- Hot replies: leads at the Replied stage (need action) ---
    hot_rows = (
        await db.execute(
            select(Lead, Company.name)
            .outerjoin(Company, Lead.company_id == Company.id)
            .where(Lead.archived.is_(False), Lead.stage == "replied")
            .order_by(
                (Lead.value_inr.is_(None)),  # False(0) first → non-null leads first
                Lead.value_inr.desc(),
                Lead.id.asc(),
            )
        )
    ).all()
    hot_replies: list[HotReplyItem] = []
    for lead, company_name in hot_rows:
        full = f"{lead.first_name} {lead.last_name}".strip() or (lead.email or f"Lead #{lead.id}")
        hot_replies.append(
            HotReplyItem(
                lead_id=lead.id,
                name=full,
                company=company_name,
                title=lead.title,
                campaign_name=names.get(lead.campaign_id) if lead.campaign_id else None,
                value_inr=lead.value_inr,
                unibox_url=_UNIBOX_URL,
                lead_url=f"/leads/{lead.id}",
            )
        )

    return DashboardSummary(
        active_campaigns=active_campaigns,
        overall_reply_rate=total_row.reply_rate,
        overall_positive_rate=total_row.positive_rate,
        funnels=funnels,
        goal=goal,
        credit_burn=credit_burn,
        hot_replies=hot_replies,
    )
