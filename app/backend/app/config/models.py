"""Pydantic V2 request/response shapes for /api/config/*."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CatalogItemRow(BaseModel):
    id: int
    kind: str
    name: str
    value: str | None = None
    archived: bool
    created_at: str
    updated_at: str


class CatalogItemCreate(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=160)
    value: str | None = Field(default=None, max_length=2000)


class CatalogItemUpdate(BaseModel):
    # All optional — only provided fields are applied (PATCH semantics).
    name: str | None = Field(default=None, min_length=1, max_length=160)
    value: str | None = Field(default=None, max_length=2000)
    archived: bool | None = None
