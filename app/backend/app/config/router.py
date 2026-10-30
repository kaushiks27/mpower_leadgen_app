"""Admin-only catalog CRUD.

GET    /api/config/items            list (optional ?kind=&include_archived=)
POST   /api/config/items            create
PATCH  /api/config/items/{id}       edit name/value/archive (soft-archive only)

No hard delete — archiving is reversible (campaigns will reference these rows).
Deterministic ordering: (kind, name, id) stable sort.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import require_role
from app.config.models import CatalogItemCreate, CatalogItemRow, CatalogItemUpdate
from app.config.orm import CATALOG_KINDS, CatalogItem
from app.db import get_session

router = APIRouter(
    prefix="/api/config",
    tags=["config"],
    dependencies=[Depends(require_role("admin"))],
)


def _row(item: CatalogItem) -> CatalogItemRow:
    return CatalogItemRow(
        id=item.id,
        kind=item.kind,
        name=item.name,
        value=item.value,
        archived=bool(item.archived),
        created_at=item.created_at.isoformat() if item.created_at else "",
        updated_at=item.updated_at.isoformat() if item.updated_at else "",
    )


@router.get("/items", response_model=list[CatalogItemRow])
async def list_items(
    kind: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_session),
) -> list[CatalogItemRow]:
    stmt = select(CatalogItem)
    if kind is not None:
        if kind not in CATALOG_KINDS:
            raise HTTPException(status_code=400, detail="invalid kind")
        stmt = stmt.where(CatalogItem.kind == kind)
    if not include_archived:
        stmt = stmt.where(CatalogItem.archived.is_(False))
    stmt = stmt.order_by(CatalogItem.kind, CatalogItem.name, CatalogItem.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [_row(r) for r in rows]


@router.post("/items", response_model=CatalogItemRow, status_code=201)
async def create_item(
    payload: CatalogItemCreate, db: AsyncSession = Depends(get_session)
) -> CatalogItemRow:
    kind = (payload.kind or "").strip()
    name = payload.name.strip()
    if kind not in CATALOG_KINDS:
        raise HTTPException(status_code=400, detail="invalid kind")
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    value = payload.value.strip() if payload.value else None
    item = CatalogItem(kind=kind, name=name, value=value)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _row(item)


@router.patch("/items/{item_id}", response_model=CatalogItemRow)
async def update_item(
    item_id: int,
    payload: CatalogItemUpdate,
    db: AsyncSession = Depends(get_session),
) -> CatalogItemRow:
    item = await db.get(CatalogItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        item.name = name
    if payload.value is not None:
        item.value = payload.value.strip() or None
    if payload.archived is not None:
        item.archived = payload.archived
    await db.commit()
    await db.refresh(item)
    return _row(item)
