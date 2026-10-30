"""Lead engine — list / board / detail / stage-move, for any signed-in user.

GET   /api/leads/meta            pipeline stages + flag keys (server is SSOT)
GET   /api/leads                 list (?stage= &q= &include_archived=)
GET   /api/leads/board           leads grouped by stage (non-archived)
GET   /api/leads/{id}            detail + audit timeline
PATCH /api/leads/{id}            move stage / set flags / archive (audited)

No hard delete (archive only). Free drag: any valid stage is accepted; the funnel
order is NOT enforced this slice. Every stage/flag/archive change writes a
`lead_events` row (who/when/from->to). Deterministic ordering throughout.
Suppressed badge is computed against the active suppression list (one-way read
of the suppression module).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.auth.orm import User
from app.auth.permissions import require_role
from app.campaigns.orm import Campaign  # one-way read: resolve campaign name
from app.db import get_session
from app.enrichment.verify_client import ELIGIBLE_STATUSES  # send-eligible bands
from app.leads.models import (
    LeadDetail,
    LeadEventRow,
    LeadRow,
    LeadUpdate,
)
from app.leads.orm import LEAD_FLAGS, PIPELINE_STAGES, Lead, LeadEvent
from app.suppression.normalize import normalize_email, normalize_linkedin
from app.suppression.orm import SuppressionEntry

router = APIRouter(
    prefix="/api/leads",
    tags=["leads"],
    dependencies=[Depends(get_current_user)],  # any signed-in user (admin or rep)
)


def _actor_name(user: User) -> str:
    return f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email


async def _campaign_names(db: AsyncSession) -> dict[int, str]:
    """Map campaign_id -> name for resolving the central list's campaign column."""
    rows = (await db.execute(select(Campaign.id, Campaign.name))).all()
    return {cid: name for cid, name in rows}


async def _campaign_owners(db: AsyncSession) -> dict[int, str | None]:
    """Map campaign_id -> free-text owner (S-7) for the master-list owner column."""
    rows = (await db.execute(select(Campaign.id, Campaign.owner))).all()
    return {cid: owner for cid, owner in rows}


async def _suppressed_keys(db: AsyncSession) -> tuple[set[str], set[str]]:
    """Active suppression values, split into (emails, linkedin) normalized sets."""
    rows = (
        await db.execute(
            select(SuppressionEntry).where(SuppressionEntry.active.is_(True))
        )
    ).scalars().all()
    emails = {r.value for r in rows if r.kind == "email"}
    links = {r.value for r in rows if r.kind == "linkedin_url"}
    return emails, links


def _is_suppressed(
    lead: Lead, emails: set[str], links: set[str]
) -> bool:
    em = normalize_email(lead.email)
    if em and em in emails:
        return True
    li = normalize_linkedin(lead.linkedin_url)
    if li and li in links:
        return True
    return False


def _row(
    lead: Lead,
    emails: set[str],
    links: set[str],
    campaigns: dict[int, str] | None = None,
    owners: dict[int, str | None] | None = None,
) -> LeadRow:
    full = f"{lead.first_name or ''} {lead.last_name or ''}".strip()
    campaigns = campaigns or {}
    owners = owners or {}
    return LeadRow(
        id=lead.id,
        first_name=lead.first_name or "",
        last_name=lead.last_name or "",
        full_name=full or "(no name)",
        email=lead.email,
        email_status=lead.email_status,
        phone=lead.phone,
        linkedin_url=lead.linkedin_url,
        icebreaker=lead.icebreaker,
        title=lead.title,
        location=lead.location,
        category=lead.category,
        customer_type=lead.customer_type,
        customer_item_id=lead.customer_item_id,
        company_id=lead.company_id,
        company_name=lead.company.name if lead.company else None,
        campaign_id=lead.campaign_id,
        campaign_name=campaigns.get(lead.campaign_id) if lead.campaign_id else None,
        campaign_owner=owners.get(lead.campaign_id) if lead.campaign_id else None,
        value_inr=lead.value_inr,
        stage=lead.stage,
        bounced=bool(lead.bounced),
        unsubscribed=bool(lead.unsubscribed),
        not_interested=bool(lead.not_interested),
        suppressed=_is_suppressed(lead, emails, links),
        source=lead.source,
        archived=bool(lead.archived),
        created_at=lead.created_at.isoformat() if lead.created_at else "",
        updated_at=lead.updated_at.isoformat() if lead.updated_at else "",
    )


@router.get("/meta")
async def leads_meta() -> dict[str, list[str]]:
    return {"stages": list(PIPELINE_STAGES), "flags": list(LEAD_FLAGS)}


def _base_query():
    return select(Lead).options(selectinload(Lead.company))


def _ordered(stmt):
    # Deterministic: by last name, first name, id (stable tiebreaker).
    return stmt.order_by(Lead.last_name, Lead.first_name, Lead.id)


@router.get("", response_model=list[LeadRow])
async def list_leads(
    stage: str | None = Query(default=None),
    q: str | None = Query(default=None),
    campaign_id: int | None = Query(default=None),
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
) -> list[LeadRow]:
    stmt = _base_query()
    if not include_archived:
        stmt = stmt.where(Lead.archived.is_(False))
    if stage:
        if stage not in PIPELINE_STAGES:
            raise HTTPException(status_code=400, detail=f"unknown stage: {stage}")
        stmt = stmt.where(Lead.stage == stage)
    if campaign_id is not None:
        stmt = stmt.where(Lead.campaign_id == campaign_id)
    stmt = _ordered(stmt)
    leads = (await db.execute(stmt)).scalars().all()

    needle = (q or "").strip().lower()
    if needle:
        def _match(lead: Lead) -> bool:
            hay = " ".join(
                [
                    lead.first_name or "",
                    lead.last_name or "",
                    lead.email or "",
                    lead.company.name if lead.company else "",
                ]
            ).lower()
            return needle in hay

        leads = [x for x in leads if _match(x)]

    emails, links = await _suppressed_keys(db)
    campaigns = await _campaign_names(db)
    owners = await _campaign_owners(db)
    return [_row(x, emails, links, campaigns, owners) for x in leads]


def _board_ordered(stmt):
    """Pipeline ordering: highest value first, NULLs last, id as stable tiebreak.

    `value_inr.is_(None)` ascending puts non-null values first (False=0) and the
    unset ones last (True=1); within each group value descends. Deterministic —
    same input always yields the same column order (exact-math rule).
    """
    return stmt.order_by(
        Lead.value_inr.is_(None),
        Lead.value_inr.desc(),
        Lead.id,
    )


@router.get("/board")
async def board(
    owner: list[str] | None = Query(default=None),
    campaign_id: list[int] | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
) -> dict:
    stmt = _board_ordered(_base_query().where(Lead.archived.is_(False)))
    if campaign_id:
        stmt = stmt.where(Lead.campaign_id.in_(campaign_id))
    leads = (await db.execute(stmt)).scalars().all()
    emails, links = await _suppressed_keys(db)
    campaigns = await _campaign_names(db)
    owners = await _campaign_owners(db)

    # Owner filter (OR within the group): keep leads whose campaign owner is in
    # the selected set. Done in Python against the resolved owner map.
    if owner:
        wanted = {o.strip() for o in owner if o and o.strip()}
        if wanted:
            leads = [
                ld
                for ld in leads
                if (owners.get(ld.campaign_id) if ld.campaign_id else None) in wanted
            ]

    columns: dict[str, list] = {s: [] for s in PIPELINE_STAGES}
    for lead in leads:
        col = lead.stage if lead.stage in columns else PIPELINE_STAGES[0]
        columns[col].append(_row(lead, emails, links, campaigns, owners).model_dump())

    # Distinct filter options for the board's filter bar (deterministic order).
    owner_options = sorted({o for o in owners.values() if o})
    campaign_options = [
        {"id": cid, "name": campaigns[cid]}
        for cid in sorted(campaigns, key=lambda c: (campaigns[c].lower(), c))
    ]
    return {
        "stages": list(PIPELINE_STAGES),
        "columns": columns,
        "owner_options": owner_options,
        "campaign_options": campaign_options,
    }


@router.get(
    "/addable",
    response_model=list[LeadRow],
    dependencies=[Depends(require_role("admin"))],
)
async def addable_leads(
    require_icebreaker: bool = Query(default=True),
    category: str | None = Query(default=None),
    customer_type: str | None = Query(default=None),
    country: str | None = Query(default=None),
    q: str | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
) -> list[LeadRow]:
    """08062026_cr CR-2 — master leads eligible to PULL into a campaign.

    Eligible = unassigned (contact-once) + not archived + send-eligible band
    (valid/catch_all = SalesPath Sure/Likely) + non-blank email. When the target
    campaign requires an icebreaker, the lead must also have one. Used by both the
    create-campaign modal and the detail Add-Leads picker (admin-only).
    """
    stmt = (
        _base_query()
        .where(
            Lead.campaign_id.is_(None),
            Lead.archived.is_(False),
            Lead.email_status.in_(ELIGIBLE_STATUSES),
            Lead.email.isnot(None),
            Lead.email != "",
        )
    )
    if require_icebreaker:
        stmt = stmt.where(Lead.icebreaker.isnot(None), Lead.icebreaker != "")
    if category and category.strip():
        stmt = stmt.where(Lead.category == category.strip())
    if customer_type and customer_type.strip():
        stmt = stmt.where(Lead.customer_type == customer_type.strip())
    if country and country.strip():
        stmt = stmt.where(Lead.location == country.strip())
    stmt = _ordered(stmt)
    leads = (await db.execute(stmt)).scalars().all()

    needle = (q or "").strip().lower()
    if needle:
        def _match(ld: Lead) -> bool:
            hay = " ".join(
                [
                    ld.first_name or "",
                    ld.last_name or "",
                    ld.email or "",
                    ld.company.name if ld.company else "",
                ]
            ).lower()
            return needle in hay

        leads = [x for x in leads if _match(x)]

    emails, links = await _suppressed_keys(db)
    return [_row(x, emails, links) for x in leads]


async def _get(db: AsyncSession, lead_id: int) -> Lead | None:
    stmt = (
        select(Lead)
        .options(selectinload(Lead.company), selectinload(Lead.events))
        .where(Lead.id == lead_id)
    )
    return (await db.execute(stmt)).scalars().first()


@router.get("/{lead_id}", response_model=LeadDetail)
async def get_lead(
    lead_id: int, db: AsyncSession = Depends(get_session)
) -> LeadDetail:
    lead = await _get(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    emails, links = await _suppressed_keys(db)
    campaigns = await _campaign_names(db)
    owners = await _campaign_owners(db)
    base = _row(lead, emails, links, campaigns, owners)
    events = [
        LeadEventRow(
            id=e.id,
            kind=e.kind,
            from_value=e.from_value,
            to_value=e.to_value,
            actor_name=e.actor_name,
            created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in sorted(lead.events, key=lambda e: e.id)
    ]
    return LeadDetail(**base.model_dump(), events=events)


@router.patch("/{lead_id}", response_model=LeadDetail)
async def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> LeadDetail:
    lead = await _get(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    actor = _actor_name(user)

    if payload.stage is not None and payload.stage != lead.stage:
        if payload.stage not in PIPELINE_STAGES:
            raise HTTPException(
                status_code=400, detail=f"unknown stage: {payload.stage}"
            )
        db.add(
            LeadEvent(
                lead_id=lead.id,
                kind="stage_change",
                from_value=lead.stage,
                to_value=payload.stage,
                actor_user_id=user.id,
                actor_name=actor,
            )
        )
        lead.stage = payload.stage

    for flag in LEAD_FLAGS:
        new_val = getattr(payload, flag)
        if new_val is not None and bool(getattr(lead, flag)) != bool(new_val):
            db.add(
                LeadEvent(
                    lead_id=lead.id,
                    kind="flag_change",
                    from_value=f"{flag}={getattr(lead, flag)}",
                    to_value=f"{flag}={new_val}",
                    actor_user_id=user.id,
                    actor_name=actor,
                )
            )
            setattr(lead, flag, new_val)

    # S-7 deal-value edit. `clear_value` clears it; otherwise an int sets it.
    # Money is load-bearing → record a `value_change` audit event (who/when/from).
    new_value = None if payload.clear_value else payload.value_inr
    if (payload.clear_value or payload.value_inr is not None) and lead.value_inr != new_value:
        db.add(
            LeadEvent(
                lead_id=lead.id,
                kind="value_change",
                from_value=str(lead.value_inr) if lead.value_inr is not None else "",
                to_value=str(new_value) if new_value is not None else "",
                actor_user_id=user.id,
                actor_name=actor,
            )
        )
        lead.value_inr = new_value

    # S-7 inline icebreaker edit (non-load-bearing copy; trimmed, blank clears).
    if payload.icebreaker is not None:
        lead.icebreaker = payload.icebreaker.strip() or None

    if payload.archived is not None and bool(lead.archived) != bool(payload.archived):
        db.add(
            LeadEvent(
                lead_id=lead.id,
                kind="archived",
                from_value=str(lead.archived),
                to_value=str(payload.archived),
                actor_user_id=user.id,
                actor_name=actor,
            )
        )
        lead.archived = payload.archived

    await db.commit()
    # expire_on_commit=False keeps the prior (pre-event) `events` collection
    # cached on the identity-map instance; expire so the reload sees new events.
    db.expire_all()
    fresh = await _get(db, lead_id)
    assert fresh is not None
    emails, links = await _suppressed_keys(db)
    campaigns = await _campaign_names(db)
    owners = await _campaign_owners(db)
    base = _row(fresh, emails, links, campaigns, owners)
    events = [
        LeadEventRow(
            id=e.id,
            kind=e.kind,
            from_value=e.from_value,
            to_value=e.to_value,
            actor_name=e.actor_name,
            created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in sorted(fresh.events, key=lambda e: e.id)
    ]
    return LeadDetail(**base.model_dump(), events=events)
