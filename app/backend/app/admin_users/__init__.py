"""Admin-users feature package. Re-exports the router for `main.py`."""

from app.admin_users.router import router

__all__ = ["router"]
