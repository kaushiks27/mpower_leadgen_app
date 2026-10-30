"""Pydantic V2 request/response shapes for /api/settings/*.

Keys are write-only: responses NEVER carry the secret — only provider, a masked
last-4, whether it is set, and where it resolves from (db | env | none).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class KeyStatus(BaseModel):
    provider: str
    is_set: bool
    last4: str | None = None
    source: str  # "db" | "env" | "none"


class SetKeyPayload(BaseModel):
    api_key: str = Field(min_length=1, max_length=512)
