"""Generate-Leads orchestration — build query, run Apify, dedup, write leads.

Pure-ish: all network I/O is injected via `runner` (default hits Apify) so the
whole flow is unit-tested without spending credits. Dedup is the EXISTING
`leads.dedup.dedup_key` + the central `leads.dedup_key` unique constraint —
global contact-once. A person already captured by ANY campaign is skipped (stays
with the first campaign), so re-clicks top up without duplicating.

Counts are plain integers (no money, no floats). New leads land in stage `new`,
`source="apify"`, tagged with the campaign, each with a `created` audit event.
The LLM is NOT in this path — nothing here is an auto pipeline decision.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.orm import Campaign, CampaignIcpFilter, CampaignRole
from app.config.orm import CatalogItem
from app.leads.dedup import dedup_key
from app.leads.orm import Company, Lead, LeadEvent
from app.scraping.apify_client import run_actor
from app.scraping.models import GenerateRequest, GenerateResult, GenerateStatus
from app.scraping.query import build_search_input
from app.settings.keys import resolve_api_key

# A runner takes the actor-input dict and returns raw dataset records.
Runner = Callable[[dict], Awaitable[list[dict]]]


class MissingKeyError(RuntimeError):
    """No Apify API key is configured (Settings or env)."""


class ScrapeError(RuntimeError):
    """Generation could not proceed (bad campaign, Apify failure, etc.)."""


def _first(rec: dict, *keys: str) -> str | None:
    """Return the first non-empty string among the candidate keys."""
    for k in keys:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def map_person(rec: dict) -> dict | None:
    """Defensively map one raw Apify/Apollo record to lead fields.

    Returns None when the record is not a dict. Missing fields become None; the
    caller still tries to dedup (name+company may suffice). Field-name variants
    are covered because actor output keys are not contractually stable.
    """
    if not isinstance(rec, dict):
        return None

    first = _first(rec, "first_name", "firstName", "given_name")
    last = _first(rec, "last_name", "lastName", "family_name")
    if not first and not last:
        full = _first(rec, "name", "full_name", "fullName")
        if full:
            parts = full.split()
            first = parts[0]
            last = " ".join(parts[1:]) if len(parts) > 1 else ""

    company = _first(
        rec, "organization_name", "company_name", "company", "organization"
    )
    if company is None:
        org = rec.get("organization")
        if isinstance(org, dict):
            company = _first(org, "name")

    location = _first(rec, "location", "city", "contact_location")
    if location is None:
        bits = [
            rec.get("city"),
            rec.get("state"),
            rec.get("country"),
        ]
        joined = ", ".join(b.strip() for b in bits if isinstance(b, str) and b.strip())
        location = joined or None

    return {
        "first_name": first or "",
        "last_name": last or "",
        "email": _first(rec, "email", "email_address", "work_email"),
        "phone": _first(rec, "phone", "phone_number", "mobile"),
        "linkedin_url": _first(rec, "linkedin_url", "linkedin", "linkedinUrl"),
        "title": _first(rec, "title", "headline", "job_title", "jobTitle"),
        "location": location,
        "company_name": company,
    }


async def campaign_lead_count(db: AsyncSession, campaign_id: int) -> int:
    """Non-archived leads tagged to this campaign (= its progress)."""
    stmt = select(func.count(Lead.id)).where(
        Lead.campaign_id == campaign_id, Lead.archived.is_(False)
    )
    return int((await db.execute(stmt)).scalar_one())


async def _selected_role_names(db: AsyncSession, campaign_id: int) -> list[str]:
    """Names of non-archived role catalog items linked to this campaign."""
    rows = (
        await db.execute(
            select(CatalogItem.name)
            .join(CampaignRole, CampaignRole.catalog_item_id == CatalogItem.id)
            .where(
                CampaignRole.campaign_id == campaign_id,
                CatalogItem.archived.is_(False),
            )
            .order_by(CatalogItem.name, CatalogItem.id)
        )
    ).all()
    return [r[0] for r in rows]


async def _selected_icp_keywords(db: AsyncSession, campaign_id: int) -> list[str]:
    """Drone-anchored keyword specs for the campaign's selected ICP filters.

    Uses each ICP filter's `value` (the drone-anchored Apify keywords, S-5d)
    when set, falling back to the display `name` only if value is blank. The
    keyword string is split on commas downstream in build_search_input.
    """
    rows = (
        await db.execute(
            select(CatalogItem.name, CatalogItem.value)
            .join(
                CampaignIcpFilter,
                CampaignIcpFilter.catalog_item_id == CatalogItem.id,
            )
            .where(
                CampaignIcpFilter.campaign_id == campaign_id,
                CatalogItem.archived.is_(False),
            )
            .order_by(CatalogItem.name, CatalogItem.id)
        )
    ).all()
    return [(value.strip() if value and value.strip() else name) for name, value in rows]


async def _targeting(
    db: AsyncSession, campaign: Campaign
) -> tuple[str | None, list[str], list[str]]:
    """Resolve (geography_name, role names, ICP keyword specs).

    Roles: the campaign's selected roles; if NONE are selected, fall back to
    ALL active roles (S-5b decision — empty = search-all, preserves prior
    behaviour for campaigns created before per-campaign selection existed).
    ICP filters: the campaign's selected ICP segments' drone-anchored keywords
    (S-5d) — the sole company signal. Target category is intentionally dropped
    (would broaden the OR-matched company search beyond drone).
    """
    geo = await db.get(CatalogItem, campaign.geography_id)

    roles = await _selected_role_names(db, campaign.id)
    if not roles:  # no per-campaign selection -> search all active roles
        all_rows = (
            await db.execute(
                select(CatalogItem.name)
                .where(
                    CatalogItem.kind == "role", CatalogItem.archived.is_(False)
                )
                .order_by(CatalogItem.name, CatalogItem.id)
            )
        ).all()
        roles = [r[0] for r in all_rows]

    icp_keywords = await _selected_icp_keywords(db, campaign.id)

    return (geo.name if geo else None, roles, icp_keywords)


async def _get_or_create_company(
    db: AsyncSession, name: str | None, cache: dict[str, Company]
) -> Company | None:
    if not name or not name.strip():
        return None
    key = " ".join(name.strip().lower().split())
    if key in cache:
        return cache[key]
    # Match an existing company case-insensitively before creating a new row.
    existing = (
        await db.execute(
            select(Company).where(func.lower(Company.name) == key)
        )
    ).scalars().first()
    company = existing or Company(name=name.strip())
    if existing is None:
        db.add(company)
        await db.flush()
    cache[key] = company
    return company


# S-5c: a campaign must have a buyer-company signal before it can scrape, or
# the Apollo actor returns title-prominent noise (VCs/investors) instead of
# real buyers. The signal is "at least one ICP filter selected" — the segment
# that describes who buys (e.g. Drone OEMs / Operators / Distributors).
NO_SIGNAL_MESSAGE = (
    "Select at least one ICP filter on this campaign and click Save changes "
    "before generating — it tells the search what kind of company to find."
)


async def _icp_count(db: AsyncSession, campaign_id: int) -> int:
    """How many ICP filters are selected (and saved) for this campaign."""
    stmt = select(func.count(CampaignIcpFilter.id)).where(
        CampaignIcpFilter.campaign_id == campaign_id
    )
    return int((await db.execute(stmt)).scalar_one())


async def get_status(db: AsyncSession, campaign: Campaign) -> GenerateStatus:
    total = await campaign_lead_count(db, campaign.id)
    target = campaign.target_lead_count or 0
    remaining = max(0, target - total) if target else 0
    target_met = bool(target) and total >= target
    has_signal = (await _icp_count(db, campaign.id)) > 0

    reason: str | None = None
    if target_met:
        reason = "target_met"  # grey out — limit hit
    elif not has_signal:
        reason = "no_company_signal"  # block — no buyer signal yet
    can = reason is None
    return GenerateStatus(
        campaign_total=total,
        target=target,
        remaining=remaining,
        can_generate=can,
        reason=reason,
    )


async def _default_runner(actor_input: dict) -> list[dict]:
    token = resolve_api_key("apify")
    if not token:
        raise MissingKeyError("Apify API key not set — add it in Settings.")
    return await run_actor(token, actor_input)


async def generate_leads(
    db: AsyncSession,
    campaign_id: int,
    req: GenerateRequest,
    *,
    runner: Runner | None = None,
) -> GenerateResult:
    """Run one Generate-Leads pass for a campaign. Returns deterministic counts."""
    run = runner or _default_runner

    campaign = await db.get(Campaign, campaign_id)
    if campaign is None or campaign.archived:
        raise ScrapeError("campaign not found")

    # S-5c guard: refuse to spend Apify credits on a no-signal search. Reading
    # the SAVED campaign here is deliberate — unsaved form selections never
    # reach generation, so this also forces the user to save before running.
    if (await _icp_count(db, campaign_id)) == 0:
        raise ScrapeError(NO_SIGNAL_MESSAGE)

    target = campaign.target_lead_count or 0
    current = await campaign_lead_count(db, campaign_id)

    if target and current >= target:
        return GenerateResult(
            requested=0, fetched=0, created=0, skipped_duplicates=0,
            skipped_no_identity=0, campaign_total=current, target=target,
            remaining=0, can_generate=False,
            message="Target already met — raise the target to generate more.",
        )

    remaining = (target - current) if target else req.cap
    effective_cap = min(req.cap, remaining) if target else req.cap

    geography, roles, icp_keywords = await _targeting(db, campaign)
    actor_input = build_search_input(
        role_names=roles,
        geography=geography,
        icp_keywords=icp_keywords,
        fetch_count=effective_cap,
        active_90d=req.active_90d,
    )

    raw = await run(actor_input)  # MissingKeyError / ApifyError bubble to router

    created = 0
    dupes = 0
    no_id = 0
    company_cache: dict[str, Company] = {}
    seen_keys: set[str] = set()

    for rec in raw:
        if created >= effective_cap:
            break
        person = map_person(rec)
        if person is None:
            no_id += 1
            continue
        try:
            key = dedup_key(
                first_name=person["first_name"],
                last_name=person["last_name"],
                email=person["email"],
                linkedin_url=person["linkedin_url"],
                company_name=person["company_name"],
            )
        except ValueError:
            no_id += 1
            continue

        if key in seen_keys:  # duplicate within this same batch
            dupes += 1
            continue
        exists = (
            await db.execute(select(Lead.id).where(Lead.dedup_key == key))
        ).first()
        if exists:
            dupes += 1
            seen_keys.add(key)
            continue

        company = await _get_or_create_company(
            db, person["company_name"], company_cache
        )
        lead = Lead(
            first_name=person["first_name"],
            last_name=person["last_name"],
            email=person["email"],
            phone=person["phone"],
            linkedin_url=person["linkedin_url"],
            title=person["title"],
            location=person["location"],
            company=company,
            campaign_id=campaign_id,
            dedup_key=key,
            stage="new",
            source="apify",
            # S-6: keep the raw scraped record (sorted JSON) so S-7 can write an
            # accurate icebreaker from the lead's headline/bio/role. No extra cost.
            scrape_raw=_dump_raw(rec),
        )
        db.add(lead)
        await db.flush()
        db.add(
            LeadEvent(
                lead_id=lead.id,
                kind="created",
                from_value=None,
                to_value=f"apify scrape (campaign {campaign_id})",
                actor_user_id=None,
                actor_name="Apify scrape",
            )
        )
        seen_keys.add(key)
        created += 1

    await db.commit()

    new_total = await campaign_lead_count(db, campaign_id)
    new_remaining = max(0, target - new_total) if target else 0
    can_generate = (target == 0) or (new_total < target)
    return GenerateResult(
        requested=effective_cap,
        fetched=len(raw),
        created=created,
        skipped_duplicates=dupes,
        skipped_no_identity=no_id,
        campaign_total=new_total,
        target=target,
        remaining=new_remaining,
        can_generate=can_generate,
        message=_summary(created, dupes, no_id, new_total, target),
    )


def _dump_raw(rec: dict) -> str | None:
    """Serialize one raw scraped record to sorted JSON for S-7 (best-effort)."""
    try:
        return json.dumps(rec, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return None


async def run_generate_job(
    db: AsyncSession,
    job_id: int,
    campaign_id: int,
    req: GenerateRequest,
    *,
    runner: Runner | None = None,
) -> None:
    """Background-job body wrapping `generate_leads` with progress reporting.

    Lets the Generate-Leads click run server-side (survives a closed tab) while
    the popup polls the job. The actual scrape/dedup/write logic is unchanged —
    this only feeds the job counters. Any MissingKey/Apify/Scrape error bubbles
    to the runner guard, which flips the job to `error` with the message.
    """
    from app.jobs import service as jobs_service

    await jobs_service.mark_running(
        db, job_id, total=req.cap, message="Searching Apify…"
    )
    result = await generate_leads(db, campaign_id, req, runner=runner)
    await jobs_service.update_progress(
        db, job_id,
        total=result.requested,
        processed=result.fetched,
        created_count=result.created,
        skipped_count=result.skipped_duplicates + result.skipped_no_identity,
    )
    await jobs_service.mark_done(db, job_id, message=result.message)


def _summary(created: int, dupes: int, no_id: int, total: int, target: int) -> str:
    bits = [f"{created} new"]
    if dupes:
        bits.append(f"{dupes} already in your leads")
    if no_id:
        bits.append(f"{no_id} unusable")
    progress = f"{total}/{target}" if target else f"{total} total"
    tail = " — target met" if target and total >= target else ""
    return ", ".join(bits) + f" ({progress}){tail}"
