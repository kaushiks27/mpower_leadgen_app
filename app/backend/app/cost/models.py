"""Pydantic V2 shapes for GET /api/cost/estimate.

Money fields are typed `Decimal`; Pydantic V2 serializes Decimal to a JSON
string by default, so exact precision survives the wire — the frontend renders
the strings as-is and does no money arithmetic of its own.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class CostLine(BaseModel):
    key: str
    label: str
    detail: str  # plain-language basis, e.g. "7 mailboxes × $3.9"
    usd: Decimal
    inr: Decimal


class CostEstimate(BaseModel):
    emails: int
    rate: Decimal  # INR per 1 USD
    sending_days: int
    mailboxes: int
    per_mailbox_per_day: int
    lines: list[CostLine]
    total_usd: Decimal
    total_inr: Decimal
    per_email_inr: Decimal
    per_lead_inr: Decimal
