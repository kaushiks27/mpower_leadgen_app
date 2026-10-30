"""Background-job infrastructure module.

Public surface:
- `router` — read-only job-status endpoints (registered in main.py).
- `service` — Job CRUD + progress helpers (used by feature work coroutines).
- `runner.launch` — fire-and-forget background scheduler.

INFRASTRUCTURE per OP #11: imports only `app.db`. Never imports a feature
module; features import this to enqueue + report progress.
"""

from app.jobs.router import router

__all__ = ["router"]
