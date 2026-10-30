"""Config feature package — catalog of building blocks (categories, geographies,
target roles, ICP filters) that campaigns/scrape/enrich consume in later slices.

Re-exports the router for `main.py` registration (OP #11). Self-contained:
imports only from infrastructure (`db/`, `auth/`).
"""

from app.config.router import router

__all__ = ["router"]
