"""Campaign-scoped Generate-Leads endpoints — REMOVED (08062026_cr CR-2).

The campaign page no longer generates leads; campaigns now PULL prepared leads
from the master Leads list ("Add Leads from List"). The scrape service
(`app.scraping.service`) is retained — it is still unit-tested and reused by the
master Generate-Leads flow — but the campaign-facing routes
(`POST /api/campaigns/{id}/generate-leads`, `GET …/generate-status`) are gone.

This bare router keeps the module importable + registered without exposing any
route (OP #11: only registration wiring touches main.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.permissions import require_role

router = APIRouter(
    prefix="/api/campaigns",
    tags=["scraping"],
    dependencies=[Depends(require_role("admin"))],
)
