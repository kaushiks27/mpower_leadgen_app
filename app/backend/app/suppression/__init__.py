"""Suppression feature — global do-not-contact list (email + LinkedIn URL).

Self-contained module per OP #11. Never imports other feature modules; other
modules may read its ORM one-way (e.g. `leads` resolves a suppressed badge).
"""

from __future__ import annotations

from app.suppression.router import router

__all__ = ["router"]
