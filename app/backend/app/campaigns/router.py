"""Admin-only campaign builder CRUD.

GET    /api/campaigns              list (optional ?include_archived=)
POST   /api/campaigns              create (validates 5 required + >=1 step)
GET    /api/campaigns/{id}         detail (with ordered steps)
PATCH  /api/campaigns/{id}         edit header / status / archive / replace steps

No hard delete — archiving is reversible. Deterministic ordering: campaigns by
(name, id), steps by step_order. Catalog references validated + label-resolved
one-way against the config module (campaigns -> config, never the reverse).
"""

from __future__ import annotations

from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.permissions import require_role
from app.campaigns.leadmix import derive_timezone, lead_mix
from app.campaigns.models import (
    AddLeadsRequest,
    CampaignCreate,
    CampaignDetail,
    CampaignRow,
    CampaignUpdate,
    LeadMix,
    StepIn,
    StepRow,
)
from app.campaigns.orm import (
    CAMPAIGN_STATUSES,
    SEND_DAYS,
    Campaign,
    CampaignIcpFilter,
    CampaignRole,
    CampaignStep,
)
from app.campaigns.timezones import DEFAULT_TZ
from app.config.orm import CatalogItem  # one-way read: validate kind + labels
from app.db import get_session
from app.enrichment.verify_client import ELIGIBLE_STATUSES  # send-eligible bands
from app.leads.orm import Lead  # one-way read: pull master leads into a campaign

router = APIRouter(
    prefix="/api/campaigns",
    tags=["campaigns"],
    dependencies=[Depends(require_role("admin"))],
)

_VALID_TIMEZONES = available_timezones()


def _clean_owner(owner: str | None) -> str | None:
    """Trim a free-text owner; empty/whitespace -> None (unassigned)."""
    if owner is None:
        return None
    trimmed = owner.strip()
    return trimmed or None


def _normalize_send_days(days: list[str]) -> str:
    """Validate + canonicalise weekday list to a CSV in SEND_DAYS order."""
    chosen = {d.strip().lower() for d in days}
    bad = chosen - set(SEND_DAYS)
    if bad:
        raise HTTPException(status_code=400, detail=f"invalid send day(s): {', '.join(sorted(bad))}")
    ordered = [d for d in SEND_DAYS if d in chosen]
    return ",".join(ordered)


def _split_send_days(csv: str | None) -> list[str]:
    if not csv:
        return []
    chosen = {d.strip().lower() for d in csv.split(",") if d.strip()}
    return [d for d in SEND_DAYS if d in chosen]


def _check_hours(start: int, end: int) -> None:
    if start >= end:
        raise HTTPException(
            status_code=400, detail="send start hour must be before end hour"
        )


def _check_timezone(tz: str) -> None:
    if tz not in _VALID_TIMEZONES:
        raise HTTPException(status_code=400, detail=f"unknown timezone: {tz}")


def _check_status(status: str) -> None:
    if status not in CAMPAIGN_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {', '.join(CAMPAIGN_STATUSES)}",
        )


async def _vestigial_catalog_id(db: AsyncSession) -> int:
    """A harmless value for the now-unused NOT-NULL taxonomy FK columns (CR-3).

    The create modal no longer collects category / target / geography, but the
    existing columns are NOT NULL on the live SQLite (OP#13: never rebuild/drop).
    SQLite FK enforcement is off, so any int satisfies the constraint — we use the
    smallest existing catalog id (or 0 when the catalog is empty). These columns
    are vestigial; their value is never read by the new UI.
    """
    row = (await db.execute(select(CatalogItem.id).order_by(CatalogItem.id))).first()
    return int(row[0]) if row else 0


async def _require_catalog(
    db: AsyncSession, item_id: int, kind: str, label: str
) -> CatalogItem:
    item = await db.get(CatalogItem, item_id)
    if item is None or item.kind != kind or item.archived:
        raise HTTPException(
            status_code=400, detail=f"{label} must be a valid (non-archived) {kind}"
        )
    return item


async def _require_catalog_ids(
    db: AsyncSession, ids: list[int], kind: str, label: str
) -> None:
    """Validate every id is a distinct, non-archived catalog item of `kind`."""
    for item_id in ids:
        await _require_catalog(db, item_id, kind, label)


def _link_ids(links: list) -> list[int]:
    """Selected catalog ids, ordered deterministically by catalog_item_id."""
    return sorted(link.catalog_item_id for link in links)


async def _labels(db: AsyncSession, c: Campaign) -> dict[str, object]:
    role_ids = _link_ids(c.role_links)
    icp_ids = _link_ids(c.icp_links)
    ids = {c.category_id, c.target_category_id, c.geography_id, *role_ids, *icp_ids}
    rows = (
        await db.execute(select(CatalogItem).where(CatalogItem.id.in_(ids)))
    ).scalars().all()
    by_id = {r.id: r.name for r in rows}
    return {
        "category_name": by_id.get(c.category_id),
        "target_category_name": by_id.get(c.target_category_id),
        "geography_name": by_id.get(c.geography_id),
        "role_ids": role_ids,
        "icp_filter_ids": icp_ids,
        "role_names": [by_id[i] for i in role_ids if i in by_id],
        "icp_filter_names": [by_id[i] for i in icp_ids if i in by_id],
    }


def _step_rows(c: Campaign) -> list[StepRow]:
    ordered = sorted(c.steps, key=lambda s: s.step_order)
    return [
        StepRow(
            id=s.id,
            step_order=s.step_order,
            wait_days=s.wait_days,
            subject=s.subject,
            body=s.body,
        )
        for s in ordered
    ]


async def _row(db: AsyncSession, c: Campaign) -> CampaignRow:
    labels = await _labels(db, c)
    return CampaignRow(
        id=c.id,
        name=c.name,
        owner=c.owner,
        require_icebreaker=bool(c.require_icebreaker),
        category_id=c.category_id,
        target_category_id=c.target_category_id,
        geography_id=c.geography_id,
        timezone=c.timezone,
        target_lead_count=c.target_lead_count,
        send_days=_split_send_days(c.send_days),
        send_start_hour=c.send_start_hour,
        send_end_hour=c.send_end_hour,
        status=c.status,
        archived=bool(c.archived),
        step_count=len(c.steps),
        created_at=c.created_at.isoformat() if c.created_at else "",
        updated_at=c.updated_at.isoformat() if c.updated_at else "",
        **labels,
    )


async def _detail(db: AsyncSession, c: Campaign) -> CampaignDetail:
    base = await _row(db, c)
    return CampaignDetail(**base.model_dump(), steps=_step_rows(c))


async def _get_with_steps(db: AsyncSession, campaign_id: int) -> Campaign | None:
    """Load a campaign with steps + targeting links eagerly (async-safe)."""
    stmt = (
        select(Campaign)
        .options(
            selectinload(Campaign.steps),
            selectinload(Campaign.role_links),
            selectinload(Campaign.icp_links),
        )
        .where(Campaign.id == campaign_id)
    )
    return (await db.execute(stmt)).scalars().first()


def _build_role_links(role_ids: list[int]) -> list[CampaignRole]:
    return [CampaignRole(catalog_item_id=i) for i in sorted(set(role_ids))]


def _build_icp_links(icp_filter_ids: list[int]) -> list[CampaignIcpFilter]:
    return [CampaignIcpFilter(catalog_item_id=i) for i in sorted(set(icp_filter_ids))]


def _build_steps(steps: list[StepIn]) -> list[CampaignStep]:
    return [
        CampaignStep(
            step_order=i + 1,
            wait_days=s.wait_days,
            subject=s.subject.strip(),
            body=s.body.strip(),
        )
        for i, s in enumerate(steps)
    ]


@router.get("", response_model=list[CampaignRow])
async def list_campaigns(
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
) -> list[CampaignRow]:
    stmt = select(Campaign).options(
        selectinload(Campaign.steps),
        selectinload(Campaign.role_links),
        selectinload(Campaign.icp_links),
    )
    if not include_archived:
        stmt = stmt.where(Campaign.archived.is_(False))
    stmt = stmt.order_by(Campaign.name, Campaign.id)
    campaigns = (await db.execute(stmt)).scalars().all()
    return [await _row(db, c) for c in campaigns]


@router.post("", response_model=CampaignDetail, status_code=201)
async def create_campaign(
    payload: CampaignCreate, db: AsyncSession = Depends(get_session)
) -> CampaignDetail:
    """Create a campaign (08062026_cr CR-3/4/5: name + pulled leads + toggle).

    The taxonomy dropdowns / roles / ICP / status / target-count / manual timezone
    are gone from the modal. Their NOT-NULL columns are filled with sentinels
    (kept non-destructively, OP#13). Pulled lead_ids are assigned to the campaign;
    the send timezone is DERIVED from those leads' majority country. The old full
    payload still validates (back-compat) when its fields are explicitly provided.
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    _check_status(payload.status)
    _check_hours(payload.send_start_hour, payload.send_end_hour)
    send_days = _normalize_send_days(payload.send_days)

    # Validate vestigial taxonomy refs only when explicitly provided; otherwise
    # fill a harmless sentinel id (the columns are unused by the new UI).
    sentinel = await _vestigial_catalog_id(db)
    if payload.category_id is not None:
        await _require_catalog(db, payload.category_id, "category", "category")
    if payload.target_category_id is not None:
        await _require_catalog(
            db, payload.target_category_id, "target_category", "target category"
        )
    if payload.geography_id is not None:
        await _require_catalog(db, payload.geography_id, "geography", "geography")
    await _require_catalog_ids(db, payload.role_ids, "role", "role")
    await _require_catalog_ids(db, payload.icp_filter_ids, "icp_filter", "ICP filter")
    for s in payload.steps:
        if not s.subject.strip() or not s.body.strip():
            raise HTTPException(
                status_code=400, detail="every step needs a subject and a body"
            )

    # Timezone: explicit (validated) > derived from pulled leads > mPower default.
    if payload.timezone:
        _check_timezone(payload.timezone)
        timezone = payload.timezone
    else:
        timezone = DEFAULT_TZ  # refined below once leads are pulled

    c = Campaign(
        name=name,
        owner=_clean_owner(payload.owner),
        require_icebreaker=bool(payload.require_icebreaker),
        category_id=payload.category_id if payload.category_id is not None else sentinel,
        target_category_id=(
            payload.target_category_id
            if payload.target_category_id is not None
            else sentinel
        ),
        geography_id=(
            payload.geography_id if payload.geography_id is not None else sentinel
        ),
        timezone=timezone,
        target_lead_count=payload.target_lead_count,
        send_days=send_days,
        send_start_hour=payload.send_start_hour,
        send_end_hour=payload.send_end_hour,
        status=payload.status,
        steps=_build_steps(payload.steps),
        role_links=_build_role_links(payload.role_ids),
        icp_links=_build_icp_links(payload.icp_filter_ids),
    )
    db.add(c)
    await db.commit()

    # Pull the selected master leads, then derive the send timezone from them
    # (unless an explicit timezone was supplied).
    if payload.lead_ids:
        await _assign_leads(db, c.id, payload.lead_ids)
    if not payload.timezone:
        c.timezone = await derive_timezone(db, c.id)
        await db.commit()

    fresh = await _get_with_steps(db, c.id)
    assert fresh is not None
    return await _detail(db, fresh)


@router.get("/{campaign_id}", response_model=CampaignDetail)
async def get_campaign(
    campaign_id: int, db: AsyncSession = Depends(get_session)
) -> CampaignDetail:
    c = await _get_with_steps(db, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return await _detail(db, c)


@router.patch("/{campaign_id}", response_model=CampaignDetail)
async def update_campaign(
    campaign_id: int,
    payload: CampaignUpdate,
    db: AsyncSession = Depends(get_session),
) -> CampaignDetail:
    c = await _get_with_steps(db, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="campaign not found")

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        c.name = name
    if payload.owner is not None:
        c.owner = _clean_owner(payload.owner)
    if payload.require_icebreaker is not None:
        c.require_icebreaker = bool(payload.require_icebreaker)
    if payload.category_id is not None:
        await _require_catalog(db, payload.category_id, "category", "category")
        c.category_id = payload.category_id
    if payload.target_category_id is not None:
        await _require_catalog(
            db, payload.target_category_id, "target_category", "target category"
        )
        c.target_category_id = payload.target_category_id
    if payload.geography_id is not None:
        await _require_catalog(db, payload.geography_id, "geography", "geography")
        c.geography_id = payload.geography_id
    if payload.timezone is not None:
        _check_timezone(payload.timezone)
        c.timezone = payload.timezone
    if payload.target_lead_count is not None:
        c.target_lead_count = payload.target_lead_count
    if payload.send_days is not None:
        c.send_days = _normalize_send_days(payload.send_days)
    # Validate hours together using new-or-existing values.
    if payload.send_start_hour is not None or payload.send_end_hour is not None:
        start = payload.send_start_hour if payload.send_start_hour is not None else c.send_start_hour
        end = payload.send_end_hour if payload.send_end_hour is not None else c.send_end_hour
        _check_hours(start, end)
        c.send_start_hour = start
        c.send_end_hour = end
    if payload.status is not None:
        _check_status(payload.status)
        c.status = payload.status
    if payload.archived is not None:
        c.archived = payload.archived
    if payload.role_ids is not None:
        await _require_catalog_ids(db, payload.role_ids, "role", "role")
        c.role_links = _build_role_links(payload.role_ids)
    if payload.icp_filter_ids is not None:
        await _require_catalog_ids(
            db, payload.icp_filter_ids, "icp_filter", "ICP filter"
        )
        c.icp_links = _build_icp_links(payload.icp_filter_ids)
    if payload.steps is not None:
        for s in payload.steps:
            if not s.subject.strip() or not s.body.strip():
                raise HTTPException(
                    status_code=400, detail="every step needs a subject and a body"
                )
        c.steps = _build_steps(payload.steps)

    await db.commit()
    fresh = await _get_with_steps(db, campaign_id)
    assert fresh is not None
    return await _detail(db, fresh)


# --------------------------------------------------------------------------- #
# 08062026_cr CR-2/3/5 — pull master leads, read-only lead-mix, derived tz.
# --------------------------------------------------------------------------- #

def _eligible_unassigned_query(require_icebreaker: bool):
    """Base query for leads that may be PULLED into a campaign (CR-2 / Q8+Q9).

    Eligible = unassigned (contact-once) + not archived + send-eligible band
    (valid/catch_all = SalesPath Sure/Likely) + non-blank email. When the campaign
    requires an icebreaker, the lead must also have one.
    """
    from sqlalchemy import and_

    stmt = (
        select(Lead)
        .options(selectinload(Lead.company))
        .where(
            Lead.campaign_id.is_(None),
            Lead.archived.is_(False),
            Lead.email_status.in_(ELIGIBLE_STATUSES),
            Lead.email.isnot(None),
            Lead.email != "",
        )
    )
    if require_icebreaker:
        stmt = stmt.where(
            and_(Lead.icebreaker.isnot(None), Lead.icebreaker != "")
        )
    return stmt


async def _assign_leads(
    db: AsyncSession, campaign_id: int, lead_ids: list[int]
) -> int:
    """Assign the eligible+unassigned subset of lead_ids to the campaign.

    Preserves contact-once: a lead already attached to ANY campaign is never
    pulled away (skipped). Returns the number actually assigned.
    """
    if not lead_ids:
        return 0
    campaign = await db.get(Campaign, campaign_id)
    require_ice = bool(campaign.require_icebreaker) if campaign else True
    stmt = _eligible_unassigned_query(require_ice).where(Lead.id.in_(set(lead_ids)))
    leads = list((await db.execute(stmt)).scalars().all())
    for ld in leads:
        ld.campaign_id = campaign_id
    if leads:
        await db.commit()
    return len(leads)


@router.get("/{campaign_id}/lead-mix", response_model=LeadMix)
async def campaign_lead_mix(
    campaign_id: int, db: AsyncSession = Depends(get_session)
) -> LeadMix:
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return LeadMix(**await lead_mix(db, campaign_id))


@router.post("/{campaign_id}/add-leads", response_model=CampaignDetail)
async def add_leads(
    campaign_id: int,
    payload: AddLeadsRequest,
    db: AsyncSession = Depends(get_session),
) -> CampaignDetail:
    """Pull the selected master leads into the campaign, then re-derive timezone."""
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    await _assign_leads(db, campaign_id, payload.lead_ids)
    # Re-derive the send timezone from the (now larger) lead set.
    c.timezone = await derive_timezone(db, campaign_id)
    await db.commit()
    fresh = await _get_with_steps(db, campaign_id)
    assert fresh is not None
    return await _detail(db, fresh)
