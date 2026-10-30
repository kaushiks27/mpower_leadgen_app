"""Campaigns feature module (S-3).

Admin-only campaign builder: a campaign = mPower category × target category ×
geography × send timezone + an optional send window + a configurable N-step
email sequence (each step = wait-days + subject + body, static placeholders).

Per OP #11 this module is self-contained and imports ONE direction only:
campaigns → infrastructure (db, auth) + the foundational config catalog
(read-only, for validation + label resolution). config/settings NEVER import
campaigns.
"""

from __future__ import annotations

from app.campaigns.router import router

__all__ = ["router"]
