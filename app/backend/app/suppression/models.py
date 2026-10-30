"""Pydantic V2 request/response shapes for /api/suppression/*."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SuppressionCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=16)  # email | linkedin_url
    value: str = Field(min_length=1, max_length=320)
    reason: str | None = Field(default=None, max_length=160)


class SuppressionRow(BaseModel):
    id: int
    kind: str
    value: str
    reason: str | None = None
    active: bool
    created_by_name: str | None = None
    created_at: str
