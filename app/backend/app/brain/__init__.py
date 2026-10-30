"""mPower's Brain — proprietary knowledge base module.

First surface: the **Products & Services** catalog (mPower's own offerings),
synced from the live site via Apify + verified line-by-line by Claude into a
data-confidence SalesPath band. Future sub-tabs (Competitors, OEMs, …) land here
as the standalone discovery engine graduates from the CLI prototype.

Self-contained (OP #11): imports only infrastructure (db, jobs, settings.keys,
auth) — never another feature module. Owns its own thin Apify + Claude clients.
"""

from app.brain.router import router

__all__ = ["router"]
