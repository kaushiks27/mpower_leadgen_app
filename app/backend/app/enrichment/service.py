"""Apollo enrich + MillionVerifier verify orchestration (background-job body).

Flow per campaign click: select the campaign's un-enriched, non-archived leads
(cap-limited), then for each lead — guarded by the per-provider monthly ceiling —
call Apollo to attach email/phone, then (if an email is found) MillionVerifier to
stamp an `email_status`. Only `valid` emails become Instantly-eligible (S-8); the
rest carry the "unverified" tag and stay visible.

Determinism: credits are integer counts (1 per Apollo match + 1 per MV check);
ceiling checks + the eligibility map are pure. The LLM is NOT in this path. A
lead's `enriched_at` is set ONLY after a successful Apollo call, so a crash mid-
batch never double-charges — the user just re-clicks and un-enriched leads run.

Network I/O is injected (`matcher`, `verifier`, `warner`) so the whole flow is
unit-tested with fakes — no live call, no credits spent in tests.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.orm import Campaign
from app.enrichment import credits
from app.enrichment.apollo_client import ApolloError, match_person
from app.enrichment.models import EnrichStatus
from app.enrichment.verify_client import (
    ELIGIBLE_STATUSES,
    UNKNOWN,
    VerifyError,
    is_eligible,
    verify_email,
)
from app.jobs import service as jobs_service
from app.leads.orm import Lead
from app.settings.keys import resolve_api_key

# Injectables: lead-hint -> {email, phone, headline, title}; email -> status;
# warner(provider, used, limit) -> None (best-effort budget-warning email).
Matcher = Callable[[dict], Awaitable[dict]]
Verifier = Callable[[str], Awaitable[str]]
Warner = Callable[[str, int, int], Awaitable[None]]


class EnrichError(RuntimeError):
    """Enrichment cannot proceed (no key, ceiling already full, bad campaign)."""


def _lead_hint(lead: Lead) -> dict:
    return {
        "first_name": lead.first_name or "",
        "last_name": lead.last_name or "",
        "organization_name": lead.company.name if lead.company else "",
        "domain": lead.company.domain if lead.company else "",
        "linkedin_url": lead.linkedin_url or "",
        "email": lead.email or "",
    }


async def _un_enriched(db: AsyncSession, campaign_id: int, limit: int) -> list[Lead]:
    from sqlalchemy.orm import selectinload

    stmt = (
        select(Lead)
        .options(selectinload(Lead.company))
        .where(
            Lead.campaign_id == campaign_id,
            Lead.archived.is_(False),
            Lead.enriched_at.is_(None),
        )
        .order_by(Lead.id)
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _count(db: AsyncSession, campaign_id: int, *, only_un_enriched=False) -> int:
    stmt = select(func.count(Lead.id)).where(
        Lead.campaign_id == campaign_id, Lead.archived.is_(False)
    )
    if only_un_enriched:
        stmt = stmt.where(Lead.enriched_at.is_(None))
    return int((await db.execute(stmt)).scalar_one())


async def _eligible_count(db: AsyncSession, campaign_id: int) -> int:
    stmt = select(func.count(Lead.id)).where(
        Lead.campaign_id == campaign_id,
        Lead.archived.is_(False),
        Lead.email_status.in_(ELIGIBLE_STATUSES),
    )
    return int((await db.execute(stmt)).scalar_one())


async def enrich_status(db: AsyncSession, campaign: Campaign) -> EnrichStatus:
    total = await _count(db, campaign.id)
    un = await _count(db, campaign.id, only_un_enriched=True)
    eligible = await _eligible_count(db, campaign.id)
    period = credits.current_period()

    reason: str | None = None
    if un == 0:
        reason = "nothing_to_enrich"
    elif not resolve_api_key("apollo"):
        reason = "missing_apollo_key"
    elif not resolve_api_key("millionverifier"):
        reason = "missing_mv_key"
    elif await credits.would_exceed(db, "apollo", 1, period):
        reason = "apollo_ceiling"
    return EnrichStatus(
        campaign_total=total,
        un_enriched=un,
        eligible=eligible,
        can_enrich=reason is None,
        reason=reason,
    )


def _default_matcher() -> Matcher:
    async def _m(hint: dict) -> dict:
        token = resolve_api_key("apollo")
        if not token:
            raise EnrichError("Apollo API key not set — add it in Settings.")
        return await match_person(token, hint)

    return _m


def _default_verifier() -> Verifier:
    async def _v(email: str) -> str:
        token = resolve_api_key("millionverifier")
        if not token:
            raise EnrichError("MillionVerifier API key not set — add it in Settings.")
        return await verify_email(token, email)

    return _v


async def _default_warner(provider: str, used: int, limit: int) -> None:
    """Best-effort Resend warning to all admins. Never raises into the job."""
    from app.auth.orm import User
    from app.email import EmailDeliveryError, send_email

    import app.db as db_mod

    pct = credits.usage_pct(used, limit)
    subject = f"[mPower] {provider} credits at {pct}% of the monthly ceiling"
    text = (
        f"Heads up: {provider} has used {used} of {limit} credits this month "
        f"({pct}%). New runs are blocked once the ceiling is reached. "
        f"Raise the ceiling in Settings if you need more."
    )
    html = f"<p>{text}</p>"
    try:
        async with db_mod.async_session() as db:
            admins = (
                (await db.execute(select(User).where(User.role == "admin")))
                .scalars()
                .all()
            )
        for a in admins:
            if a.email:
                send_email(to=a.email, subject=subject, html=html, text=text)
    except EmailDeliveryError:
        pass  # logged-only / transport failure must not break the job
    except Exception:  # noqa: BLE001 — warning is best-effort
        pass


async def run_enrich_job(
    db: AsyncSession,
    job_id: int,
    campaign_id: int,
    cap: int,
    *,
    matcher: Matcher | None = None,
    verifier: Verifier | None = None,
    warner: Warner | None = None,
    now: datetime | None = None,
) -> None:
    """Background-job body: enrich + verify up to `cap` un-enriched leads."""
    match = matcher or _default_matcher()
    verify = verifier or _default_verifier()
    warn = warner or _default_warner
    period = credits.current_period(now)

    leads = await _un_enriched(db, campaign_id, cap)
    await jobs_service.mark_running(
        db, job_id, total=len(leads), message=f"Enriching {len(leads)} leads…"
    )

    processed = found = phones = verified = errors = used = 0
    stopped = ""

    for lead in leads:
        # Apollo ceiling guard — stop the whole run before spending past 100%.
        if await credits.would_exceed(db, "apollo", 1, period):
            stopped = "Apollo monthly credit ceiling reached — run stopped."
            break

        try:
            person = await match(_lead_hint(lead))
        except (ApolloError, EnrichError) as e:
            errors += 1
            processed += 1
            await jobs_service.update_progress(
                db, job_id, processed=processed, error_count=errors,
                credits_used=used, message=f"Apollo error on a lead: {e}",
            )
            continue

        # Charge 1 Apollo credit for the completed match call.
        used += 1
        total_apollo = await credits.record_usage(db, "apollo", period, 1)
        await _maybe_warn(db, "apollo", period, total_apollo, warn)

        email = person.get("email")
        if email:
            lead.email = email
            found += 1
        if person.get("phone") and not lead.phone:
            lead.phone = person["phone"]
            phones += 1
        # Keep Apollo's headline/title for S-7 icebreakers (merge into scrape_raw).
        _merge_scrape_meta(lead, person)

        # Verify the email (only `valid` is Instantly-eligible).
        if email:
            if await credits.would_exceed(db, "millionverifier", 1, period):
                lead.email_status = UNKNOWN  # MV ceiling hit — leave unverified
            else:
                try:
                    status = await verify(email)
                except (VerifyError, EnrichError):
                    status = UNKNOWN
                else:
                    used += 1
                    total_mv = await credits.record_usage(
                        db, "millionverifier", period, 1
                    )
                    await _maybe_warn(db, "millionverifier", period, total_mv, warn)
                    if is_eligible(status):
                        verified += 1
                lead.email_status = status
                lead.email_checked_at = func.now()
        else:
            lead.email_status = "no_email"

        lead.enriched_at = func.now()
        processed += 1
        await db.commit()
        await jobs_service.update_progress(
            db, job_id,
            processed=processed, created_count=found, error_count=errors,
            credits_used=used,
            message=f"{processed}/{len(leads)} · {found} emails · {verified} verified",
        )

    summary = (
        f"{processed} processed · {found} emails ({verified} verified) · "
        f"{phones} phones · {used} credits"
    )
    if stopped:
        summary = f"{stopped} {summary}"
    await jobs_service.update_progress(
        db, job_id, processed=processed, created_count=found,
        skipped_count=0, error_count=errors, credits_used=used,
    )
    await jobs_service.mark_done(db, job_id, message=summary)


async def _maybe_warn(
    db: AsyncSession, provider: str, period: str, used: int, warn: Warner
) -> None:
    if await credits.should_warn(db, provider, period):
        limit = await credits.get_ceiling(db, provider)
        await warn(provider, used, limit)
        await credits.mark_warned(db, provider, period)


def _merge_scrape_meta(lead: Lead, person: dict) -> None:
    """Fold Apollo's headline/title into the lead's stored scrape_raw (S-7)."""
    try:
        meta = json.loads(lead.scrape_raw) if lead.scrape_raw else {}
        if not isinstance(meta, dict):
            meta = {}
    except (ValueError, TypeError):
        meta = {}
    if person.get("headline"):
        meta.setdefault("apollo_headline", person["headline"])
    if person.get("title") and not lead.title:
        lead.title = person["title"]
    lead.scrape_raw = json.dumps(meta, sort_keys=True) if meta else lead.scrape_raw


# Re-export so the default UTC clock is overridable in tests via the module.
_now = lambda: datetime.now(timezone.utc)  # noqa: E731
