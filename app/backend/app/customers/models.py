"""Pydantic V2 request/response shapes for the Customers surface."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.jobs.models import JobOut

SCOPES = ("local", "global")
# Fields a user may inline-edit (and that get sync-locked once edited).
EDITABLE_FIELDS = ("name", "country", "category", "ctype", "website")


class CustomerDevInfo(BaseModel):
    """Read-only dev reference: the real discovery strategy + Claude classifier prompt."""

    search_actor: str
    crawl_actor: str
    sources: list[str]
    type_sources: list[str]
    sample_queries: list[str]
    enrichment_queries: list[str]
    mpower_categories: list[str]
    pipeline_steps: list[str] = []
    claude_model: str
    claude_system: str
    claude_user_template: str
    extract_model: str = ""
    extract_system: str = ""
    extract_user_template: str = ""


class ActiveSyncOut(BaseModel):
    """The in-flight sync job (if any) — lets the popup reopen after close/reload."""

    job: JobOut | None = None


class CustomerOut(BaseModel):
    id: int
    name: str
    website: str | None = None
    website_verified: bool | None = None  # stage-2 resolve: None=unchecked, True/False
    domain: str | None = None
    country: str | None = None
    phone: str | None = None
    email: str | None = None
    email_quality: str | None = None
    discovery_source: str | None = None
    scope: str
    category: str | None = None
    ctype: str | None = None
    band: str | None = None
    band_reason: str | None = None
    band_confidence: str | None = None
    locked_fields: list[str] = []
    manual: bool
    archived: bool
    source_url: str | None = None
    created_at: str
    updated_at: str


class CustomerSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total: int = 0
    local: int = 0
    # serialized as "global" for the frontend ("global" is a reserved word in py).
    global_: int = Field(default=0, serialization_alias="global")
    manual: int = 0
    banded: int = 0
    last_synced: str | None = None


class ManualAddRequest(BaseModel):
    name: str
    website: str | None = None
    country: str | None = None
    category: str | None = None
    ctype: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("customer name is required")
        return v


class EditRequest(BaseModel):
    name: str | None = None
    website: str | None = None
    country: str | None = None
    category: str | None = None
    ctype: str | None = None
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


class SyncRequest(BaseModel):
    """Sync knob — how many companies to pull from EACH source/lane (Google + the 6
    multi-source lanes). Pre-filled 50 in the popup; clamped 1..1000."""

    per_source: int = 50

    @field_validator("per_source")
    @classmethod
    def _clamp(cls, v: int) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 50
        return max(1, min(1000, v))
