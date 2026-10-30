"""Instantly push orchestration — eligibility gate, push job body, start.

Reads `campaigns.orm` + `leads.orm` + `email_gen.service` one-way (newest module
imports older; nothing imports back). All push state is deterministic Python; the
only LLM output involved (the icebreaker) was written + stored at S-7 and is
merely transmitted here — it never becomes a number or a pipeline decision.

A lead is PUSHABLE when its email is verified-valid AND it has a stored icebreaker
AND a non-blank email. The "all ready" gate additionally requires that no lead is
mid-pipeline (still un-verified, or verified-with-signal but not yet icebroken);
verified leads with no scraped detail (no icebreaker possible) are EXCLUDED, not
blocking. On a successful push each pushed lead moves FORWARD to `queued` (audited;
never a backward jump) — Emailed/Replied arrive from the S-9 pull.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.campaigns.orm import Campaign
from app.email_gen.service import icebreaker_status
from app.enrichment.verify_client import ELIGIBLE_STATUSES
from app.instantly import mapper
from app.instantly.client import InstantlyClient, InstantlyClientProtocol, InstantlyError
from app.instantly.models import InstantlyState, PushStatus
from app.instantly.orm import InstantlyCampaign
from app.jobs import service as jobs_service
from app.leads.orm import PIPELINE_STAGES, Lead, LeadEvent
from app.settings.keys import resolve_api_key

_QUEUED = "queued"
_QUEUED_INDEX = PIPELINE_STAGES.index(_QUEUED)
_PUSH_ACTOR = "system (Instantly push)"
_BULK_BATCH = 1000  # Instantly /leads/add cap per request


class PushError(RuntimeError):
    """Push/start cannot proceed (no key, not pushed, gate fail)."""


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


async def _get_row(db: AsyncSession, campaign_id: int) -> InstantlyCampaign | None:
    stmt = select(InstantlyCampaign).where(
        InstantlyCampaign.campaign_id == campaign_id
    )
    return (await db.execute(stmt)).scalars().first()


def _state_from_row(row: InstantlyCampaign | None) -> InstantlyState:
    if row is None:
        return InstantlyState(state="not_pushed")
    return InstantlyState(
        state=row.status,
        instantly_campaign_id=row.instantly_campaign_id,
        error=row.error,
        leads_pushed=row.leads_pushed or 0,
        leads_failed=row.leads_failed or 0,
        pushed_at=_iso(row.pushed_at),
        started_at=_iso(row.started_at),
    )


def _is_locked(row: InstantlyCampaign | None) -> bool:
    """A push is LOCKED (no re-push, Start available) only after it SUCCEEDED.

    Success = a draft with at least one lead pushed and none failed, OR a live
    campaign. A failed/partial push (status `error`, or a draft that pushed 0 /
    had failures — e.g. Instantly lead-limit) is NOT locked: the campaign page
    returns to "Create Instantly Campaign" so the user can fix the cause + retry.
    A retry REUSES the already-created remote draft (no duplicate campaigns).
    """
    if row is None:
        return False
    if row.status == "live":
        return True
    if row.status == "draft" and (row.leads_pushed or 0) > 0 and (row.leads_failed or 0) == 0:
        return True
    return False


async def _pushable_leads(
    db: AsyncSession, campaign_id: int, *, require_icebreaker: bool = True
) -> list[Lead]:
    """Send-eligible leads (Sure + on-domain Likely) with non-blank email, ordered
    by id. An icebreaker is required ONLY when the campaign's require_icebreaker
    toggle is ON (08062026_cr CR-2 / Q9)."""
    stmt = (
        select(Lead)
        .options(selectinload(Lead.company))
        .where(
            Lead.campaign_id == campaign_id,
            Lead.archived.is_(False),
            Lead.email_status.in_(ELIGIBLE_STATUSES),
        )
        .order_by(Lead.id)
    )
    leads = list((await db.execute(stmt)).scalars().all())
    return [
        ld
        for ld in leads
        if (ld.email or "").strip()
        and (not require_icebreaker or (ld.icebreaker or "").strip())
    ]


async def _unverified_count(db: AsyncSession, campaign_id: int) -> int:
    """Non-archived campaign leads not yet verified (email_status NULL).

    These are still in progress (need enrich + verify), so they BLOCK the gate.
    A lead with any email_status set has already been verified — terminal.
    """
    from sqlalchemy import func as _func

    stmt = select(_func.count()).select_from(Lead).where(
        Lead.campaign_id == campaign_id,
        Lead.archived.is_(False),
        Lead.email_status.is_(None),
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def push_status(db: AsyncSession, campaign: Campaign) -> PushStatus:
    """Button-state snapshot for the campaign page."""
    row = await _get_row(db, campaign.id)
    base = _state_from_row(row)

    ice = await icebreaker_status(db, campaign)
    require_ice = bool(campaign.require_icebreaker)  # CR-2 / Q9

    valid_total = ice.written + ice.missing + ice.no_source  # send-eligible band
    non_valid = max(0, ice.campaign_total - valid_total)
    unverified = await _unverified_count(db, campaign.id)  # still in progress
    terminal_non_valid = max(0, non_valid - unverified)  # can't be sent

    if require_ice:
        # Eligible = send-eligible WITH an icebreaker. A lead blocks the gate while
        # still in progress: not yet verified, or valid-with-signal but no
        # icebreaker yet. No-detail (no_source) + terminal non-valid are EXCLUDED.
        eligible = ice.written
        pending = unverified + ice.missing
        excluded = ice.no_source + terminal_non_valid
    else:
        # Icebreaker optional: every send-eligible lead is pushable. Only
        # not-yet-verified leads block; terminal non-valid are excluded.
        eligible = valid_total
        pending = unverified
        excluded = terminal_non_valid

    has_key = bool(resolve_api_key("instantly"))

    # A SUCCESSFUL push locks re-push and reveals Start. A failed/partial push is
    # NOT locked — the page returns to "Create Instantly Campaign" for a retry.
    if _is_locked(row):
        return PushStatus(
            **base.model_dump(),
            campaign_total=ice.campaign_total,
            eligible=eligible,
            pending=pending,
            excluded=excluded,
            can_push=False,
            can_start=base.state == "draft",
            reason="already_pushed",
        )

    # Not pushed, or a prior push failed (status `error`, or empty draft). Run the
    # readiness gate so the user can (re)push.
    if not has_key:
        reason = "missing_key"
    elif ice.campaign_total == 0 or eligible == 0:
        reason = "needs_leads"
    elif pending > 0:
        reason = "not_ready"
    else:
        reason = None

    return PushStatus(
        **base.model_dump(),
        campaign_total=ice.campaign_total,
        eligible=eligible,
        pending=pending,
        excluded=excluded,
        can_push=reason is None,
        can_start=False,
        reason=reason,
    )


def _resolve_client(client: InstantlyClientProtocol | None) -> InstantlyClientProtocol:
    if client is not None:
        return client
    token = resolve_api_key("instantly")
    if not token:
        raise PushError("Instantly API key not set — add it in Settings.")
    return InstantlyClient(token)


def _maybe_queue(db: AsyncSession, lead: Lead) -> None:
    """Move a pushed lead FORWARD to queued (audited). No backward jump."""
    try:
        cur_index = PIPELINE_STAGES.index(lead.stage)
    except ValueError:
        cur_index = -1
    if cur_index >= _QUEUED_INDEX:
        return
    db.add(
        LeadEvent(
            lead_id=lead.id,
            kind="stage_change",
            from_value=lead.stage,
            to_value=_QUEUED,
            actor_user_id=None,
            actor_name=_PUSH_ACTOR,
        )
    )
    lead.stage = _QUEUED


async def run_push_job(
    db: AsyncSession,
    job_id: int,
    campaign_id: int,
    *,
    client: InstantlyClientProtocol | None = None,
) -> None:
    """Background-job body: create the Instantly campaign (draft) + upload leads."""
    # Eager-load steps — async lazy-loading the relationship would raise.
    campaign = (
        await db.execute(
            select(Campaign)
            .options(selectinload(Campaign.steps))
            .where(Campaign.id == campaign_id)
        )
    ).scalars().first()
    if campaign is None or campaign.archived:
        await jobs_service.mark_error(db, job_id, "campaign not found")
        return

    row = await _get_row(db, campaign_id)
    if _is_locked(row):
        await jobs_service.mark_error(
            db, job_id, "campaign already pushed to Instantly"
        )
        return

    try:
        api = _resolve_client(client)
    except PushError as e:
        await jobs_service.mark_error(db, job_id, str(e))
        return

    # Steps in canonical order (relationship is ordered by step_order).
    steps = list(campaign.steps)
    leads = await _pushable_leads(
        db, campaign_id, require_icebreaker=bool(campaign.require_icebreaker)
    )
    if not leads:
        await jobs_service.mark_error(db, job_id, "no eligible leads to push")
        return

    await jobs_service.mark_running(
        db, job_id, total=len(leads), message="Creating Instantly campaign…"
    )

    if row is None:
        row = InstantlyCampaign(campaign_id=campaign_id, status="error")
        db.add(row)

    from sqlalchemy import func as _func

    # 1) Reuse the existing remote draft on a RETRY (no duplicate campaigns); only
    # create one on the first attempt. A failed push leaves the (empty) draft + an
    # `error` status, so the next attempt fills the SAME campaign once the user has
    # fixed the cause (e.g. freed Instantly lead quota).
    if row.instantly_campaign_id:
        instantly_id = row.instantly_campaign_id
    else:
        try:
            payload = mapper.to_campaign_payload(campaign, steps)
            instantly_id = await api.create_campaign(payload)
        except InstantlyError as e:
            row.status = "error"
            row.error = str(e)
            await db.commit()
            await jobs_service.mark_error(db, job_id, f"Instantly error: {e}")
            return
        row.instantly_campaign_id = instantly_id
        row.error = None
        row.pushed_at = _func.now()
        await db.commit()
        await db.refresh(row)  # resolve func.now() → real timestamp before reads

    # 2) Bulk-upload leads (batches of 1000), flipping each pushed lead forward to
    # queued. The bulk endpoint associates the batch via `campaign_id`.
    pushed = failed = 0
    last_error: str | None = None
    for start in range(0, len(leads), _BULK_BATCH):
        batch = leads[start : start + _BULK_BATCH]
        entries = [mapper.to_lead_payload(ld) for ld in batch]
        try:
            await api.add_leads(instantly_id, entries)
        except InstantlyError as e:
            failed += len(batch)
            last_error = str(e)
            await jobs_service.update_progress(
                db, job_id, processed=pushed + failed,
                created_count=pushed, error_count=failed,
                message=f"Instantly error uploading leads: {e}",
            )
            continue
        for lead in batch:
            _maybe_queue(db, lead)
        pushed += len(batch)
        await db.commit()
        await jobs_service.update_progress(
            db, job_id, processed=pushed + failed,
            created_count=pushed, error_count=failed,
            message=f"{pushed} pushed · {failed} failed",
        )

    row.leads_pushed = pushed
    row.leads_failed = failed
    # Only a CLEAN push (every lead in, none failed) becomes a startable draft.
    # Any failure → `error` status so the page returns to "Create Instantly
    # Campaign" for a retry (Start stays hidden). The remote draft is kept + reused.
    if failed == 0 and pushed > 0:
        row.status = "draft"
        row.error = None
    else:
        row.status = "error"
        row.error = (
            f"{failed} lead(s) failed: {last_error}" if last_error
            else "no leads were pushed"
        )
    await db.commit()

    if failed == 0 and pushed > 0:
        summary = (
            f"Draft ready in Instantly · {pushed} leads pushed. "
            f"Attach mailboxes in Instantly, then press Start."
        )
    else:
        summary = (
            f"Push stopped — {failed} lead(s) failed: {last_error}. "
            f"Fix the cause and press Create Instantly Campaign to retry."
        )
    await jobs_service.update_progress(
        db, job_id, processed=pushed + failed, created_count=pushed, error_count=failed
    )
    await jobs_service.mark_done(db, job_id, message=summary)


async def start_campaign(
    db: AsyncSession,
    campaign: Campaign,
    *,
    client: InstantlyClientProtocol | None = None,
) -> InstantlyState:
    """Activate the already-pushed Instantly campaign (Start). Synchronous."""
    from sqlalchemy import func as _func

    row = await _get_row(db, campaign.id)
    if not _is_locked(row):
        raise PushError("push the campaign to Instantly first")
    if row.status == "live":
        return _state_from_row(row)

    api = _resolve_client(client)  # raises PushError if no key
    try:
        await api.activate(row.instantly_campaign_id)
    except InstantlyError as e:
        row.status = "error"
        row.error = str(e)
        await db.commit()
        return _state_from_row(row)

    row.status = "live"
    row.error = None
    row.started_at = _func.now()
    await db.commit()
    await db.refresh(row)  # resolve func.now() → real timestamp before reads
    return _state_from_row(row)
