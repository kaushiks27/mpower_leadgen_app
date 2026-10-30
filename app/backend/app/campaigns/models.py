"""Pydantic V2 request/response shapes for /api/campaigns/*."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StepIn(BaseModel):
    # wait_days = days to wait BEFORE sending this step (step 1 = 0 = immediate).
    wait_days: int = Field(default=0, ge=0, le=365)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=10000)


class StepRow(BaseModel):
    id: int
    step_order: int
    wait_days: int
    subject: str
    body: str


class CampaignCreate(BaseModel):
    # 08062026_cr CR-3/4/5: the create modal collects only name + pulled leads +
    # the require-icebreaker toggle. The taxonomy dropdowns / roles / ICP / status
    # / target-count / manual timezone are GONE. The vestigial columns below are
    # now OPTIONAL (filled with safe sentinels when omitted, OP#13 non-destructive)
    # and validated only when explicitly provided (back-compat for the old payload).
    name: str = Field(min_length=1, max_length=160)
    owner: str | None = Field(default=None, max_length=120)  # S-7 free-text owner
    # CR-2: per-campaign icebreaker requirement (defaults ON).
    require_icebreaker: bool = True
    # CR-2: leads pulled into the campaign at creation (the modal picker).
    lead_ids: list[int] = Field(default_factory=list)
    # --- vestigial (kept for back-compat; optional) ---------------------------
    category_id: int | None = None
    target_category_id: int | None = None
    geography_id: int | None = None
    timezone: str | None = Field(default=None, max_length=64)
    target_lead_count: int = Field(default=0, ge=0, le=1_000_000)
    send_days: list[str] = Field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
    send_start_hour: int = Field(default=9, ge=0, le=23)
    send_end_hour: int = Field(default=17, ge=0, le=23)
    status: str = "draft"
    role_ids: list[int] = Field(default_factory=list)
    icp_filter_ids: list[int] = Field(default_factory=list)
    # CR-3/4/5: the email sequence is built on the DETAIL page, not at create.
    steps: list[StepIn] = Field(default_factory=list)


class CampaignUpdate(BaseModel):
    # All optional — only provided fields are applied (PATCH semantics). When
    # `steps` is provided, it replaces the entire step set.
    name: str | None = Field(default=None, min_length=1, max_length=160)
    owner: str | None = Field(default=None, max_length=120)  # S-7; "" clears it
    require_icebreaker: bool | None = None  # CR-2: editable on the detail page
    category_id: int | None = None
    target_category_id: int | None = None
    geography_id: int | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    target_lead_count: int | None = Field(default=None, ge=0, le=1_000_000)
    send_days: list[str] | None = None
    send_start_hour: int | None = Field(default=None, ge=0, le=23)
    send_end_hour: int | None = Field(default=None, ge=0, le=23)
    status: str | None = None
    archived: bool | None = None
    # S-5b: when provided, replaces the entire role / ICP selection set.
    role_ids: list[int] | None = None
    icp_filter_ids: list[int] | None = None
    steps: list[StepIn] | None = Field(default=None, min_length=1)


class CampaignRow(BaseModel):
    """List view — header + resolved labels + step count (no step bodies)."""

    id: int
    name: str
    owner: str | None = None  # S-7 free-text campaign owner
    require_icebreaker: bool = True  # CR-2 per-campaign toggle
    category_id: int
    target_category_id: int
    geography_id: int
    category_name: str | None = None
    target_category_name: str | None = None
    geography_name: str | None = None
    # S-5b: selected targeting (ids drive the form; names are display-only).
    role_ids: list[int] = Field(default_factory=list)
    icp_filter_ids: list[int] = Field(default_factory=list)
    role_names: list[str] = Field(default_factory=list)
    icp_filter_names: list[str] = Field(default_factory=list)
    timezone: str
    target_lead_count: int
    send_days: list[str]
    send_start_hour: int
    send_end_hour: int
    status: str
    archived: bool
    step_count: int
    created_at: str
    updated_at: str


class CampaignDetail(CampaignRow):
    steps: list[StepRow]


class LeadMix(BaseModel):
    """08062026_cr CR-3/5 — read-only derived summary of a campaign's lead mix."""

    categories: list[str] = Field(default_factory=list)
    customer_types: list[str] = Field(default_factory=list)  # OEM/Reseller/Distributor
    countries: list[str] = Field(default_factory=list)
    timezone: str
    lead_count: int


class AddLeadsRequest(BaseModel):
    """08062026_cr CR-2 — pull master leads into a campaign by id."""

    lead_ids: list[int] = Field(default_factory=list)
