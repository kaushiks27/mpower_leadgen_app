"""Instantly push feature module (S-8).

Public surface:
- `router` — campaign-scoped push/start/status endpoints (registered in main.py).

Per OP #11 this is a self-contained feature module. It reads `campaigns.orm`,
`leads.orm`, and `email_gen.service` ONE-WAY (newest module → older); it imports
infrastructure (`db`, `jobs`, `settings.keys`) but no module imports back from it.
"""

from app.instantly.router import router

__all__ = ["router"]
