"""Thin async Instantly v2 API client (push + pull side).

Push (S-8): create a campaign (draft), add leads, activate. Pull (S-9):
`list_leads` reads per-lead status back (reply count / lifecycle status) so the
puller can drive the pipeline. Bearer auth with the Instantly key from encrypted
Settings. The client is injected into the service (a fake is used in unit tests)
so no test ever hits the live API or spends/sends anything.

`list_leads` is a READ — it spends nothing and sends no email; it is the only
pull call this slice and is paginated via Instantly's `starting_after` cursor.

All methods raise `InstantlyError` (clean message) on transport/auth/body failure
so the router/job can surface an error pill instead of a raw 500.
"""

from __future__ import annotations

from typing import Protocol

import httpx

_BASE = "https://api.instantly.ai/api/v2"


class InstantlyError(RuntimeError):
    """Any Instantly API failure (auth, transport, non-2xx, bad body)."""


class InstantlyClientProtocol(Protocol):
    """The surface the service depends on (real client or a test fake)."""

    async def create_campaign(self, payload: dict) -> str: ...
    async def add_leads(self, instantly_campaign_id: str, leads: list[dict]) -> None: ...
    async def activate(self, instantly_campaign_id: str) -> None: ...
    async def list_leads(self, instantly_campaign_id: str) -> list[dict]: ...


class InstantlyClient:
    def __init__(self, token: str, *, timeout: float = 30.0) -> None:
        self._token = token
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _post(self, path: str, json: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{_BASE}{path}", headers=self._headers, json=json
                )
        except httpx.HTTPError as e:
            raise InstantlyError(f"could not reach Instantly: {e}") from e
        if resp.status_code >= 400:
            raise InstantlyError(
                f"Instantly returned {resp.status_code}: {resp.text[:300]}"
            )
        try:
            body = resp.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    async def create_campaign(self, payload: dict) -> str:
        """Create a draft campaign; return its Instantly id."""
        body = await self._post("/campaigns", payload)
        cid = body.get("id") or body.get("campaign_id")
        if not cid:
            raise InstantlyError("Instantly create-campaign returned no id")
        return str(cid)

    async def add_leads(self, instantly_campaign_id: str, leads: list[dict]) -> None:
        """Bulk-add leads to a campaign via POST /api/v2/leads/add.

        Instantly associates the batch through the `campaign_id` field (NOT the
        single-lead `campaign` field, which 403s with "No access to this
        campaign"). Up to 1000 leads per request.
        """
        await self._post(
            "/leads/add", {"campaign_id": instantly_campaign_id, "leads": leads}
        )

    async def activate(self, instantly_campaign_id: str) -> None:
        await self._post(f"/campaigns/{instantly_campaign_id}/activate", {})

    async def list_leads(self, instantly_campaign_id: str) -> list[dict]:
        """Read every lead on a campaign with its status fields (pull side).

        POST /api/v2/leads/list — the batch is filtered by the `campaign` field
        and paginated via the `next_starting_after` cursor (verified live 2026-06-03
        against the real workspace: response = { items: [...], next_starting_after }).
        A pure read — spends no credits and sends no email. Returns the raw lead
        dicts; the pull mapper interprets them (status enum kept out of this client).
        """
        out: list[dict] = []
        cursor: str | None = None
        # Bounded loop: at most 200 pages (200k leads) so a malformed cursor can
        # never spin forever.
        for _ in range(200):
            body: dict = {"campaign": instantly_campaign_id, "limit": 100}
            if cursor:
                body["starting_after"] = cursor
            page = await self._post("/leads/list", body)
            items = page.get("items")
            if isinstance(items, list):
                out.extend(i for i in items if isinstance(i, dict))
            cursor = page.get("next_starting_after")
            if not cursor:
                break
        return out
