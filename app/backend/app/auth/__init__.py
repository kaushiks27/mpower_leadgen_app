"""Auth feature package. Re-exports the router for `main.py` registration."""

from app.auth.router import router

__all__ = ["router"]
