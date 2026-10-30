"""Settings feature package — encrypted API-key storage + resolution.

Re-exports the router for `main.py` registration (OP #11). `resolve_api_key`
and `load_cache` are imported by main.py to wire the email key resolver at
startup, keeping `email` free of any `settings` import (feature→infra).
"""

from app.settings.router import router

__all__ = ["router"]
