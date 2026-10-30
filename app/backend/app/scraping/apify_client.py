"""Thin async Apify client — the ONLY network I/O in this module.

Isolated behind `run_actor()` so the service can be unit-tested with a fake
runner (no live call, no credits spent in tests). The default actor is the cheap
Apollo-sourced people finder recommended in the lessons doc; the id is a module
constant now and becomes Settings-configurable in a later slice.

Uses Apify's run-sync-get-dataset-items endpoint: one request runs the actor and
returns the dataset rows directly, so we never poll a run id.
"""

from __future__ import annotations

import httpx

# Default actor. Apify slugs use '~' in the API path (owner~name).
DEFAULT_ACTOR_ID = "code_crafter~leads-finder"

_BASE = "https://api.apify.com/v2/acts"


class ApifyError(RuntimeError):
    """Raised when the Apify call fails (auth, actor, or transport)."""


async def run_actor(
    token: str,
    actor_input: dict,
    *,
    actor_id: str = DEFAULT_ACTOR_ID,
    timeout: float = 120.0,
) -> list[dict]:
    """Run the actor synchronously and return its dataset items.

    Raises ApifyError on any non-2xx or transport failure so the caller can
    surface a clean message instead of leaking a raw stack trace.
    """
    url = f"{_BASE}/{actor_id}/run-sync-get-dataset-items"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, params={"token": token}, json=actor_input)
    except httpx.HTTPError as e:  # network / timeout
        raise ApifyError(f"could not reach Apify: {e}") from e

    if resp.status_code >= 400:
        raise ApifyError(
            f"Apify returned {resp.status_code}: {resp.text[:300]}"
        )
    try:
        data = resp.json()
    except ValueError as e:
        raise ApifyError("Apify returned a non-JSON body") from e

    if not isinstance(data, list):
        raise ApifyError("Apify returned an unexpected (non-list) dataset")
    return data
