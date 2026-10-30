"""Instantly pull orchestration — Sync running-campaign status into the pipeline.

Reads `campaigns.orm` + `leads.orm` + `suppression.orm` one-way (newest module
imports older; nothing imports back). Every load-bearing decision here is
DETERMINISTIC Python from `pull_mapper` — no LLM ever decides a stage or a flag.

Sync is IDEMPOTENT: it only writes when an Instantly signal implies a change the
lead hasn't already taken. Re-running with no new Instantly activity makes zero
writes. Stage moves are FORWARD-ONLY (locked Q3) — a reply/sent signal can advance
a lead but never regress it, and never overwrites a manual edit with an earlier
stage. Bounces/unsubs set a flag AND auto-suppress (contact-once); the bounce/unsub
status encoding is UNVERIFIED (see pull_mapper + KI-18) and acts only on listed codes.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.orm import User
from app.campaigns.orm import Campaign
from app.instantly import pull_mapper
from app.instantly.client import InstantlyClient, InstantlyClientProtocol, InstantlyError
from app.instantly.models import CampaignMonitor, HotReply, SyncResult
from app.instantly.orm import InstantlyCampaign, InstantlySyncState
from app.leads.orm import PIPELINE_STAGES, Lead, LeadEvent
from app.settings.keys import resolve_api_key
from app.suppression.normalize import normalize_email
from app.suppression.orm import SuppressionEntry

_REPLIED_INDEX = PIPELINE_STAGES.index("replied")
_EMAILED_INDEX = PIPELINE_STAGES.index("emailed")
_SYNC_ACTOR = "Instantly sync"
# Deep-link target for reading/replying a thread. Instantly's Unibox has no
# documented per-lead URL param, so we link to the Unibox root (KI-18); the user
# lands in their inbox and the lead is at the top of the hot-reply list.
_UNIBOX_URL = "https://app.instantly.ai/app/unibox"


class SyncError(RuntimeError):
    """Sync cannot proceed (no key, not pushed, transport failure)."""


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _actor_name(user: User) -> str:
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return f"{_SYNC_ACTOR} · {full or user.email}"


def _resolve_client(client: InstantlyClientProtocol | None) -> InstantlyClientProtocol:
    if client is not None:
        return client
    token = resolve_api_key("instantly")
    if not token:
        raise SyncError("Instantly API key not set — add it in Settings.")
    return InstantlyClient(token)


async def _push_row(db: AsyncSession, campaign_id: int) -> InstantlyCampaign | None:
    return (
        await db.execute(
            select(InstantlyCampaign).where(
                InstantlyCampaign.campaign_id == campaign_id
            )
        )
    ).scalars().first()


async def _sync_row(db: AsyncSession, campaign_id: int) -> InstantlySyncState | None:
    return (
        await db.execute(
            select(InstantlySyncState).where(
                InstantlySyncState.campaign_id == campaign_id
            )
        )
    ).scalars().first()


async def _suppress(
    db: AsyncSession, email: str | None, reason: str, user: User
) -> bool:
    """Idempotently add an email to global suppression. Returns True if newly added.

    Mirrors `suppression.router.add_suppression`: normalized email, unique
    (kind,value), reactivates a soft-removed row. A row that is already active for
    this email is a no-op (returns False) so re-syncs don't double-count.
    """
    value = normalize_email(email)
    if not value:
        return False
    existing = (
        await db.execute(
            select(SuppressionEntry).where(
                SuppressionEntry.kind == "email", SuppressionEntry.value == value
            )
        )
    ).scalars().first()
    if existing is not None:
        if existing.active:
            return False  # already suppressed — idempotent no-op
        existing.active = True
        existing.reason = reason
        return True
    db.add(
        SuppressionEntry(
            kind="email",
            value=value,
            reason=reason,
            active=True,
            created_by_id=user.id,
            created_by_name=_actor_name(user),
        )
    )
    return True


async def _campaign_leads(db: AsyncSession, campaign_id: int) -> list[Lead]:
    return list(
        (
            await db.execute(
                select(Lead)
                .options(selectinload(Lead.company))
                .where(Lead.campaign_id == campaign_id, Lead.archived.is_(False))
                .order_by(Lead.id)
            )
        ).scalars().all()
    )


def _move_stage(db: AsyncSession, lead: Lead, target: str, user: User) -> None:
    db.add(
        LeadEvent(
            lead_id=lead.id,
            kind="stage_change",
            from_value=lead.stage,
            to_value=target,
            actor_user_id=user.id,
            actor_name=_actor_name(user),
        )
    )
    lead.stage = target


def _set_flag(db: AsyncSession, lead: Lead, flag: str, user: User) -> None:
    db.add(
        LeadEvent(
            lead_id=lead.id,
            kind="flag_change",
            from_value=f"{flag}={getattr(lead, flag)}",
            to_value=f"{flag}=True",
            actor_user_id=user.id,
            actor_name=_actor_name(user),
        )
    )
    setattr(lead, flag, True)


async def sync_campaign(
    db: AsyncSession,
    campaign: Campaign,
    *,
    user: User,
    client: InstantlyClientProtocol | None = None,
) -> SyncResult:
    """Pull Instantly status for one campaign and apply it (idempotent, forward-only)."""
    row = await _push_row(db, campaign.id)
    if row is None or not row.instantly_campaign_id:
        raise SyncError("This campaign hasn't been pushed to Instantly yet.")

    api = _resolve_client(client)  # raises SyncError if no key
    try:
        raw_leads = await api.list_leads(row.instantly_campaign_id)
    except InstantlyError as e:
        raise SyncError(f"Could not read Instantly status: {e}") from e

    # Index app leads by normalized email (the match key, locked Q4).
    leads = await _campaign_leads(db, campaign.id)
    by_email: dict[str, Lead] = {}
    for ld in leads:
        key = normalize_email(ld.email)
        if key and key not in by_email:
            by_email[key] = ld

    stage_changes = newly_bounced = newly_unsub = suppressed = matched = unmatched = 0
    tot_replies = tot_bounces = tot_unsubs = 0

    for raw in raw_leads:
        signal = pull_mapper.classify_lead(raw)
        # Summary counters reflect Instantly's view over ALL pulled leads.
        tot_replies += int(signal.replied)
        tot_bounces += int(signal.bounced)
        tot_unsubs += int(signal.unsubscribed)

        lead = by_email.get(signal.email) if signal.email else None
        if lead is None:
            unmatched += 1
            continue
        matched += 1

        # Forward-only stage move (reply > sent), never regress.
        target = pull_mapper.forward_stage(lead.stage, signal)
        if target is not None:
            _move_stage(db, lead, target, user)
            stage_changes += 1

        # Bounce / unsubscribe → flag + auto-suppress (idempotent; UNVERIFIED codes).
        if signal.bounced and not lead.bounced:
            _set_flag(db, lead, "bounced", user)
            newly_bounced += 1
            if await _suppress(db, lead.email, "bounce", user):
                suppressed += 1
        if signal.unsubscribed and not lead.unsubscribed:
            _set_flag(db, lead, "unsubscribed", user)
            newly_unsub += 1
            if await _suppress(db, lead.email, "unsubscribe", user):
                suppressed += 1

    # Persist the Sync summary (separate table; created via create_all).
    sync = await _sync_row(db, campaign.id)
    if sync is None:
        sync = InstantlySyncState(campaign_id=campaign.id)
        db.add(sync)
    sync.last_synced_at = func.now()
    sync.leads_pulled = len(raw_leads)
    sync.leads_matched = matched
    sync.leads_unmatched = unmatched
    sync.replies = sum(1 for r in raw_leads if pull_mapper.classify_lead(r).replied)
    sync.bounces = sum(1 for r in raw_leads if pull_mapper.classify_lead(r).bounced)
    sync.unsubscribes = sum(
        1 for r in raw_leads if pull_mapper.classify_lead(r).unsubscribed
    )

    await db.commit()

    monitor = await build_monitor(db, campaign, row=row)
    return SyncResult(
        stage_changes=stage_changes,
        newly_bounced=newly_bounced,
        newly_unsubscribed=newly_unsub,
        suppressed=suppressed,
        leads_pulled=len(raw_leads),
        leads_matched=matched,
        leads_unmatched=unmatched,
        monitor=monitor,
    )


async def build_monitor(
    db: AsyncSession,
    campaign: Campaign,
    *,
    row: InstantlyCampaign | None = None,
) -> CampaignMonitor:
    """Snapshot one pushed campaign for the Monitor — counts DERIVED from app leads."""
    if row is None:
        row = await _push_row(db, campaign.id)
    sync = await _sync_row(db, campaign.id)
    leads = await _campaign_leads(db, campaign.id)

    def _stage_idx(s: str) -> int:
        try:
            return PIPELINE_STAGES.index(s)
        except ValueError:
            return -1

    emailed = sum(1 for ld in leads if _stage_idx(ld.stage) >= _EMAILED_INDEX)
    replied = sum(1 for ld in leads if _stage_idx(ld.stage) >= _REPLIED_INDEX)
    bounced = sum(1 for ld in leads if ld.bounced)
    unsubscribed = sum(1 for ld in leads if ld.unsubscribed)

    # Hot-reply queue = leads sitting AT `replied` (fresh, not yet manually moved
    # on to interested/won). Deterministic order by id.
    hot = [
        HotReply(
            lead_id=ld.id,
            name=f"{ld.first_name or ''} {ld.last_name or ''}".strip() or "(no name)",
            email=ld.email,
            company=ld.company.name if ld.company else None,
            title=ld.title,
            unibox_url=_UNIBOX_URL,
        )
        for ld in leads
        if ld.stage == "replied"
    ]

    return CampaignMonitor(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        state=row.status if row else "not_pushed",
        can_sync=bool(row and row.instantly_campaign_id),
        last_synced_at=_iso(sync.last_synced_at) if sync else None,
        leads_total=len(leads),
        emailed=emailed,
        replied=replied,
        bounced=bounced,
        unsubscribed=unsubscribed,
        unmatched=int(sync.leads_unmatched) if sync else 0,
        hot_replies=hot,
    )


async def monitor_list(db: AsyncSession) -> list[CampaignMonitor]:
    """Every campaign that has an Instantly row (pushed), newest campaign first."""
    rows = (
        await db.execute(
            select(InstantlyCampaign, Campaign)
            .join(Campaign, Campaign.id == InstantlyCampaign.campaign_id)
            .where(Campaign.archived.is_(False))
            .order_by(Campaign.id.desc())
        )
    ).all()
    return [await build_monitor(db, campaign, row=row) for row, campaign in rows]
