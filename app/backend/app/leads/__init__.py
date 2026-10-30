"""Leads feature — lead/company spine, dedup, pipeline board, audit timeline.

Self-contained module per OP #11. Imports infrastructure (db, auth) and reads the
suppression module one-way (normalize + suppressed badge). Other modules never
import leads.
"""

from __future__ import annotations

from app.leads.router import router

__all__ = ["router"]
