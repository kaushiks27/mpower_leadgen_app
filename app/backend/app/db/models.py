"""Shared SQLAlchemy declarative Base.

Feature ORM tables live in their own module (`<feature>/orm.py`) per
Operating Principle #11 — never in this file. They register on this shared
`Base.metadata` so `init_db` picks them up via `create_all`.
"""

from __future__ import annotations

from sqlalchemy.orm import declarative_base

Base = declarative_base()
