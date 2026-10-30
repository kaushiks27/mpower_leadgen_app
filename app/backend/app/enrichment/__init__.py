"""Enrichment feature module — Apollo enrich + MillionVerifier verify + credits.

Public surface: `router` (registered in main.py). One-way reads only (OP #11):
enrichment -> leads / campaigns / config / settings / email / jobs / infra.
Older modules NEVER import enrichment.
"""

from app.enrichment.router import router

__all__ = ["router"]
