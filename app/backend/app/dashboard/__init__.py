"""Dashboard feature package — read-only funnel + rates + goal + credit burn.

Re-exports the router for `main.py` registration (OP #11). All aggregation is
deterministic Python over persisted leads/campaigns/credit tables (no DB writes,
no live external calls, no LLM-computed numbers). One-way reads of the leads,
campaigns, and enrichment modules; never imported BY them.
"""

from app.dashboard.router import router

__all__ = ["router"]
