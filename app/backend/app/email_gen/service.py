"""Icebreaker generation orchestration (background-job body + status).

Flow per campaign click: select the campaign's non-archived leads that have NO
icebreaker yet; for each, build a real context from its columns + scraped JSON.
If there is no real signal, SKIP it (never fabricate). Otherwise ask Claude for
one line, sanitize it to a single human sentence, and store it on the lead.

Idempotent: only leads with a blank icebreaker are processed, so a re-click (or
a crash mid-batch) only writes the ones still missing — already-written leads
cost nothing. The LLM output lands ONLY in `Lead.icebreaker` (non-load-bearing);
it is never a number or a pipeline decision.

The writer is injected so the whole flow is unit-tested with a fake (no live
call, no spend).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.campaigns.orm import Campaign
from app.email_gen import prompt as prompt_mod
from app.enrichment.verify_client import ELIGIBLE_STATUSES
from app.email_gen.claude_client import ClaudeError, write_icebreaker
from app.email_gen.models import IcebreakerStatus
from app.jobs import service as jobs_service
from app.leads.orm import Lead
from app.settings.keys import resolve_api_key

# writer(system, user) -> raw model text.
Writer = Callable[[str, str], Awaitable[str]]


class IcebreakerError(RuntimeError):
    """Generation cannot proceed (no Anthropic key, bad campaign)."""


def _has_icebreaker(lead: Lead) -> bool:
    return bool(lead.icebreaker and lead.icebreaker.strip())


def _lead_context(lead: Lead) -> dict:
    return prompt_mod.extract_context(
        {
            "first_name": lead.first_name,
            "title": lead.title,
            "company": lead.company.name if lead.company else "",
            "location": lead.location,
        },
        lead.scrape_raw,
    )


# Only verified-valid emails are icebreaker-eligible: outreach is sent solely to
# send-eligible leads only (S-6) — "SalesPath Sure" (valid) + on-domain
# "SalesPath Likely" (catch_all); see verify_client.ELIGIBLE_STATUSES. Writing
# copy for anything else is wasted Claude spend. This also enforces the workflow
# order — a status is set only AFTER Generate → Apollo Enrich + MillionVerifier
# verify, so the icebreaker button stays disabled until eligible leads exist.
ELIGIBLE_EMAIL_STATUS = "valid"  # back-compat alias; gate now uses ELIGIBLE_STATUSES


async def _campaign_leads(db: AsyncSession, campaign_id: int) -> list[Lead]:
    """All non-archived campaign leads (for the total + display counts)."""
    stmt = (
        select(Lead)
        .options(selectinload(Lead.company))
        .where(Lead.campaign_id == campaign_id, Lead.archived.is_(False))
        .order_by(Lead.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _eligible_leads(db: AsyncSession, campaign_id: int) -> list[Lead]:
    """Verified-valid leads only — the icebreaker-eligible set (post-enrich)."""
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
    return list((await db.execute(stmt)).scalars().all())


async def _missing_leads(db: AsyncSession, campaign_id: int) -> list[Lead]:
    """Verified-valid campaign leads with NO icebreaker yet (deterministic order)."""
    leads = await _eligible_leads(db, campaign_id)
    return [ld for ld in leads if not _has_icebreaker(ld)]


async def _missing_leads_by_ids(
    db: AsyncSession, lead_ids: list[int]
) -> list[Lead]:
    """08062026_cr CR-2: verified-valid leads (by id) with NO icebreaker yet.

    Master Leads-page relocation of the icebreaker action. Only send-eligible
    (valid + on-domain catch_all) leads that have a real signal get a line; the
    rest are skipped (never fabricated). Deterministic order by id.
    """
    if not lead_ids:
        return []
    stmt = (
        select(Lead)
        .options(selectinload(Lead.company))
        .where(
            Lead.id.in_(set(lead_ids)),
            Lead.archived.is_(False),
            Lead.email_status.in_(ELIGIBLE_STATUSES),
        )
        .order_by(Lead.id)
    )
    leads = list((await db.execute(stmt)).scalars().all())
    return [ld for ld in leads if not _has_icebreaker(ld)]


async def icebreaker_status(db: AsyncSession, campaign: Campaign) -> IcebreakerStatus:
    total = len(await _campaign_leads(db, campaign.id))
    eligible = await _eligible_leads(db, campaign.id)
    written = sum(1 for ld in eligible if _has_icebreaker(ld))
    missing = no_source = 0
    for ld in eligible:
        if _has_icebreaker(ld):
            continue
        if prompt_mod.has_signal(_lead_context(ld)):
            missing += 1
        else:
            no_source += 1

    reason: str | None = None
    if len(eligible) == 0:
        # No verified leads yet -> the user must Generate + Enrich/verify first.
        reason = "needs_enrich"
    elif missing == 0:
        reason = "nothing_to_write"
    elif not resolve_api_key("anthropic"):
        reason = "missing_key"
    return IcebreakerStatus(
        campaign_total=total,
        missing=missing,
        no_source=no_source,
        written=written,
        can_generate=reason is None,
        reason=reason,
    )


def _default_writer() -> Writer:
    async def _w(system: str, user: str) -> str:
        token = resolve_api_key("anthropic")
        if not token:
            raise IcebreakerError("Anthropic API key not set — add it in Settings.")
        return await write_icebreaker(token, system, user)

    return _w


async def run_icebreaker_job(
    db: AsyncSession,
    job_id: int,
    campaign_id: int,
    *,
    writer: Writer | None = None,
) -> None:
    """Background-job body: write an icebreaker for every campaign lead missing one."""
    write = writer or _default_writer()
    leads = await _missing_leads(db, campaign_id)
    await _write_icebreakers(db, job_id, leads, write)


async def run_icebreaker_job_for_leads(
    db: AsyncSession,
    job_id: int,
    lead_ids: list[int],
    *,
    writer: Writer | None = None,
) -> None:
    """08062026_cr CR-2: background body for the master Leads-page bulk action.

    Writes an icebreaker for every selected verified lead that still lacks one.
    Same per-lead logic as the campaign path — only the lead set differs."""
    write = writer or _default_writer()
    leads = await _missing_leads_by_ids(db, lead_ids)
    await _write_icebreakers(db, job_id, leads, write)


async def _write_icebreakers(
    db: AsyncSession, job_id: int, leads: list[Lead], write: Writer
) -> None:
    """Shared writer loop: one sanitized icebreaker per lead with real signal."""
    await jobs_service.mark_running(
        db, job_id, total=len(leads), message=f"Writing {len(leads)} icebreakers…"
    )

    processed = written = skipped = errors = 0
    for lead in leads:
        processed += 1
        ctx = _lead_context(lead)
        # No real signal -> never fabricate a line. Count it and move on.
        if not prompt_mod.has_signal(ctx):
            skipped += 1
            await jobs_service.update_progress(
                db, job_id, processed=processed, created_count=written,
                skipped_count=skipped, error_count=errors,
                message=f"{processed}/{len(leads)} · {written} written · {skipped} skipped",
            )
            continue

        system = prompt_mod.SYSTEM_PROMPT
        user = prompt_mod.build_user_prompt(ctx)
        try:
            raw = await write(system, user)
        except (ClaudeError, IcebreakerError) as e:
            errors += 1
            await jobs_service.update_progress(
                db, job_id, processed=processed, created_count=written,
                skipped_count=skipped, error_count=errors,
                message=f"Claude error on a lead: {e}",
            )
            continue

        line = prompt_mod.sanitize(raw)
        if not line:
            errors += 1
        else:
            lead.icebreaker = line
            written += 1
            await db.commit()
        await jobs_service.update_progress(
            db, job_id, processed=processed, created_count=written,
            skipped_count=skipped, error_count=errors,
            message=f"{processed}/{len(leads)} · {written} written · {skipped} skipped",
        )

    summary = (
        f"{written} icebreakers written · {skipped} skipped (no profile detail) · "
        f"{errors} errors"
    )
    await jobs_service.update_progress(
        db, job_id, processed=processed, created_count=written,
        skipped_count=skipped, error_count=errors,
    )
    await jobs_service.mark_done(db, job_id, message=summary)
