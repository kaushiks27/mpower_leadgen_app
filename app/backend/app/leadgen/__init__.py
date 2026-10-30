"""Generate-Leads engine — finds decision-makers inside mPower's customer companies.

Self-contained feature module (OP #11): imports only infrastructure + reused
tables (leads.dedup / leads.orm, enrichment, customers.orm, brain categories via
SQL, jobs, settings, segments). No existing module imports leadgen.
"""

from __future__ import annotations

from app.leadgen.router import router

__all__ = ["router"]
