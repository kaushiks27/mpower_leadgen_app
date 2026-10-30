"""Pydantic V2 request/response shapes for the Brain catalog."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, field_validator

from app.jobs.models import JobOut

KINDS = ("product", "service")


class CatalogDevInfo(BaseModel):
    """Read-only dev reference: the real Apify sourcing strategy + Claude prompt."""

    apify_actor: str
    apify_input: str            # pretty JSON of the actual crawl input
    products_url: str
    service_slugs: list[str]
    claude_model: str
    claude_system: str
    claude_user_template: str


class ActiveSyncOut(BaseModel):
    """The in-flight sync job (if any) — lets the popup reopen after close/reload."""

    job: JobOut | None = None


class CatalogItemOut(BaseModel):
    id: int
    kind: str
    name: str
    handle: str | None = None
    category: str | None = None
    price_inr: str | None = None
    price_locked: bool = False
    band: str | None = None
    band_reason: str | None = None
    band_confidence: str | None = None
    manual: bool
    archived: bool
    source_url: str | None = None
    created_at: str
    updated_at: str


class CatalogSummary(BaseModel):
    products: int = 0
    services: int = 0
    manual: int = 0
    banded: int = 0
    last_synced: str | None = None


class ManualAddRequest(BaseModel):
    kind: str
    name: str
    price_inr: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in KINDS:
            raise ValueError("kind must be 'product' or 'service'")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name is required")
        return v

    @field_validator("price_inr")
    @classmethod
    def _price(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            d = Decimal(str(v))
        except (InvalidOperation, ValueError) as e:
            raise ValueError("price must be a number") from e
        if d < 0:
            raise ValueError("price must be >= 0")
        return str(d)  # exact decimal string, never float


class EditRequest(BaseModel):
    name: str | None = None
    price_inr: str | None = None
    archived: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("name cannot be blank")
        return v

    @field_validator("price_inr")
    @classmethod
    def _price(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            d = Decimal(str(v))
        except (InvalidOperation, ValueError) as e:
            raise ValueError("price must be a number") from e
        if d < 0:
            raise ValueError("price must be >= 0")
        return str(d)


class SyncRequest(BaseModel):
    """Empty body — the sync is derived from the live mPower site (idempotent)."""
