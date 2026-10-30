"""Global do-not-contact list CRUD — any signed-in user (admin or rep).

GET    /api/suppression                 list active entries (?include_inactive=)
POST   /api/suppression                 add (normalizes + dedupes; reactivates a
                                         soft-removed match instead of erroring)
DELETE /api/suppression/{id}            soft-deactivate (auditable; not a hard delete)

Values are normalized before storage/compare via `suppression.normalize` so the
same person is matched regardless of case/URL format.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.orm import User
from app.db import get_session
from app.suppression.models import SuppressionCreate, SuppressionRow
from app.suppression.normalize import normalize_email, normalize_linkedin
from app.suppression.orm import SUPPRESSION_KINDS, SuppressionEntry

router = APIRouter(
    prefix="/api/suppression",
    tags=["suppression"],
    dependencies=[Depends(get_current_user)],  # any signed-in user
)


def _normalize(kind: str, value: str) -> str:
    if kind == "email":
        out = normalize_email(value)
    elif kind == "linkedin_url":
        out = normalize_linkedin(value)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {', '.join(SUPPRESSION_KINDS)}",
        )
    if not out:
        raise HTTPException(status_code=400, detail="value is empty after normalizing")
    return out


def _row(e: SuppressionEntry) -> SuppressionRow:
    return SuppressionRow(
        id=e.id,
        kind=e.kind,
        value=e.value,
        reason=e.reason,
        active=bool(e.active),
        created_by_name=e.created_by_name,
        created_at=e.created_at.isoformat() if e.created_at else "",
    )


@router.get("", response_model=list[SuppressionRow])
async def list_suppression(
    include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
) -> list[SuppressionRow]:
    stmt = select(SuppressionEntry)
    if not include_inactive:
        stmt = stmt.where(SuppressionEntry.active.is_(True))
    # Deterministic order: kind, then value, then id.
    stmt = stmt.order_by(
        SuppressionEntry.kind, SuppressionEntry.value, SuppressionEntry.id
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_row(e) for e in rows]


@router.post("", response_model=SuppressionRow, status_code=201)
async def add_suppression(
    payload: SuppressionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> SuppressionRow:
    kind = payload.kind.strip().lower()
    if kind not in SUPPRESSION_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {', '.join(SUPPRESSION_KINDS)}",
        )
    value = _normalize(kind, payload.value)
    reason = (payload.reason or "").strip() or "manual"

    existing = (
        await db.execute(
            select(SuppressionEntry).where(
                SuppressionEntry.kind == kind, SuppressionEntry.value == value
            )
        )
    ).scalars().first()
    if existing is not None:
        # Reactivate a soft-removed match rather than violating the unique key.
        existing.active = True
        existing.reason = reason
        await db.commit()
        await db.refresh(existing)
        return _row(existing)

    name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
    entry = SuppressionEntry(
        kind=kind,
        value=value,
        reason=reason,
        active=True,
        created_by_id=user.id,
        created_by_name=name,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _row(entry)


@router.delete("/{entry_id}", status_code=204)
async def remove_suppression(
    entry_id: int, db: AsyncSession = Depends(get_session)
) -> None:
    entry = await db.get(SuppressionEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="suppression entry not found")
    entry.active = False  # soft-deactivate — auditable, not a hard delete
    await db.commit()
