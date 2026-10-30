"""Pydantic V2 request/response shapes for the Generate-Leads surface."""

from __future__ import annotations

from pydantic import BaseModel


class CustomerLite(BaseModel):
    """A pickable customer row (the company a decision-maker works at)."""

    id: int
    name: str
    type: str | None = None      # OEM | Reseller | Distributor (the Type column)
    country: str | None = None
    category: str | None = None
    website: str | None = None
    band: str | None = None      # genuine-customer band (advisory; informational)


class RoleGroupOut(BaseModel):
    """One decision-maker role group + its title variants (for the picker)."""

    group: str
    titles: list[str]


class ListsResponse(BaseModel):
    """Everything the Generate-Leads form needs to render its filters."""

    categories: list[str]
    categories_grouped: dict[str, list[str]] = {"product": [], "service": []}
    types: list[str]
    countries: list[str]
    customers: list[CustomerLite]
    roles: list[RoleGroupOut]


class GenerateRequest(BaseModel):
    """Start a Generate-Leads run over the selected customers + role groups."""

    categories: list[str] = []
    types: list[str] = []
    country: str | None = None
    customer_ids: list[int] = []
    role_groups: list[str] = []
    cap: int | None = None       # total leads to create this run (None = config default)


class WidenRequest(BaseModel):
    """The user's answer to the in-app 'search saturated — widen?' confirmation."""

    job_id: int
    approve: bool


class DevInfo(BaseModel):
    """Read-only dev reference: the real actors + a sample input + the widen prompt."""

    linkedin_actor: str
    fallback_actors: list[str]
    widen_model: str
    sample_actor_input: dict
    widen_system: str
    widen_user_template: str
    pipeline_steps: list[str] = []
