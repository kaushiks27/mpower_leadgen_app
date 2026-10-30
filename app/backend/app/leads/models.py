"""Pydantic V2 request/response shapes for /api/leads/*."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LeadRow(BaseModel):
    id: int
    first_name: str
    last_name: str
    full_name: str
    email: str | None = None
    email_status: str | None = None  # S-6 MV verdict; valid|risky|invalid|unknown|no_email
    phone: str | None = None
    linkedin_url: str | None = None
    icebreaker: str | None = None
    title: str | None = None
    location: str | None = None  # CR-6: company country (structured), not city
    # CR-6 structured taxonomy carried from the originating customer (advisory).
    category: str | None = None
    customer_type: str | None = None  # OEM|Reseller|Distributor
    customer_item_id: int | None = None
    company_id: int | None = None
    company_name: str | None = None
    campaign_id: int | None = None
    campaign_name: str | None = None  # resolved from campaigns (one-way read)
    campaign_owner: str | None = None  # S-7 free-text owner of the lead's campaign
    value_inr: int | None = None  # S-7 potential deal value, exact INR int (no float)
    stage: str
    bounced: bool
    unsubscribed: bool
    not_interested: bool
    suppressed: bool  # computed against the active suppression list
    source: str | None = None
    archived: bool
    created_at: str
    updated_at: str


class LeadEventRow(BaseModel):
    id: int
    kind: str
    from_value: str | None = None
    to_value: str | None = None
    actor_name: str | None = None
    created_at: str


class LeadDetail(LeadRow):
    events: list[LeadEventRow]


class LeadUpdate(BaseModel):
    # PATCH semantics — only provided fields applied. A stage change writes an
    # audit event; flag changes write audit events; a value change writes a
    # `value_change` event (money is load-bearing — auditable).
    stage: str | None = None
    bounced: bool | None = None
    unsubscribed: bool | None = None
    not_interested: bool | None = None
    archived: bool | None = None
    # S-7 potential deal value, exact whole INR (>= 0). Send null to clear.
    value_inr: int | None = Field(default=None, ge=0, le=10_000_000_000)
    # Distinguishes "value_inr omitted" (don't touch) from "value_inr: null"
    # (clear it) — Pydantic can't tell those apart from the field alone.
    clear_value: bool = False
    # S-7 inline edit of the AI-written icebreaker (non-load-bearing copy).
    icebreaker: str | None = Field(default=None, max_length=2000)
