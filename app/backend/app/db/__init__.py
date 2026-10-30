"""Async SQLAlchemy engine + session factory + create_all bootstrap.

Feature modules import `async_session` for their own use; routers depend on
`get_session` for per-request sessions. `init_db()` runs from FastAPI lifespan.

OP #13 — never wipe the dev DB. `create_all` only adds *missing* tables; it
never drops or truncates. Destructive migrations require explicit user OK.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models import Base

# Additive-only column migrations (OP #13 — never drop/truncate). create_all
# adds missing TABLES but not missing COLUMNS on existing tables, so a
# persistent dev/prod SQLite needs these ADD COLUMN statements to self-heal on
# boot. Each entry: (table, column, column-def). Idempotent — skipped when the
# column already exists. ADD COLUMN only; nothing here ever removes data.
_ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("campaigns", "target_lead_count", "INTEGER NOT NULL DEFAULT 0"),
    ("leads", "campaign_id", "INTEGER"),
    # S-6 enrichment/verification fields on Lead (ADD COLUMN only, OP#13-safe).
    ("leads", "email_status", "VARCHAR(16)"),
    ("leads", "email_checked_at", "DATETIME"),
    ("leads", "enriched_at", "DATETIME"),
    ("leads", "scrape_raw", "TEXT"),
    # S-7: potential deal value (exact INR int) + free-text campaign owner.
    ("leads", "value_inr", "INTEGER"),
    ("campaigns", "owner", "VARCHAR(120)"),
    # 08062026_cr CR-6: structured lead taxonomy carried from the originating
    # CustomerItem (category + OEM/Reseller/Distributor type) + the link FK used
    # for robust going-forward attribution. `location` (existing) is repurposed to
    # the customer's company country. All additive (self-heal), non-destructive.
    ("leads", "category", "VARCHAR(160)"),
    ("leads", "customer_type", "VARCHAR(12)"),       # OEM|Reseller|Distributor
    ("leads", "customer_item_id", "INTEGER"),        # FK → customer_items.id (nullable)
    # 08062026_cr CR-2/Q9: per-campaign "require icebreaker" toggle. Drives the
    # Add-Leads picker eligibility + the Instantly push gate. Default 1 (ON) to
    # preserve the prior verified+icebroken send discipline.
    ("campaigns", "require_icebreaker", "INTEGER NOT NULL DEFAULT 1"),
    # Brain catalog: manual price override that survives a re-sync.
    ("brain_catalog_items", "price_locked", "INTEGER NOT NULL DEFAULT 0"),
    # Competitors: stage-2 website-resolve flag (NULL/1/0). Self-heals existing DBs.
    ("competitor_items", "website_verified", "INTEGER"),
    # S-CR2 multi-source: which lane first discovered the competitor (provenance).
    ("competitor_items", "discovery_source", "VARCHAR(32)"),  # maps|linkedin|indiamart|thomasnet|europages|wlw|google
    # Generate-Leads: per-company user decision on the Claude "widen" prompt.
    ("leadgen_runs", "widen_states_json", "TEXT"),
    # S-MS1 multi-source discovery: company contact + which lane discovered the row.
    ("customer_items", "phone", "VARCHAR(64)"),
    ("customer_items", "email", "VARCHAR(255)"),
    ("customer_items", "email_quality", "VARCHAR(16)"),   # MillionVerifier band: valid|catch_all|...
    ("customer_items", "discovery_source", "VARCHAR(32)"),  # maps|linkedin|indiamart|thomasnet|europages|wlw|google
)

DEFAULT_DB_URL = "sqlite+aiosqlite:///./mpower_leadgen.db"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DB_URL)


engine = create_async_engine(_database_url(), future=True)
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def init_db() -> None:
    # Import feature ORM modules so their tables register on Base.metadata.
    import app.auth.orm  # noqa: F401
    import app.brain.orm  # noqa: F401  (mPower's Brain — products/services catalog)
    import app.competitors.orm  # noqa: F401  (mPower's Brain — competitors)
    import app.customers.orm  # noqa: F401  (mPower's Brain — customers / OEMs + channel)
    import app.campaigns.orm  # noqa: F401
    import app.config.orm  # noqa: F401
    import app.enrichment.orm  # noqa: F401  (S-6 credit ceilings + usage)
    import app.instantly.orm  # noqa: F401  (S-8 Instantly push link table)
    import app.jobs.orm  # noqa: F401  (S-6 background jobs)
    import app.leadgen.orm  # noqa: F401  (Generate-Leads run tracking)
    import app.leads.orm  # noqa: F401
    import app.settings.orm  # noqa: F401
    import app.suppression.orm  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_additive_columns(conn)


async def _ensure_additive_columns(conn) -> None:
    """ADD COLUMN for any missing additive column (idempotent, SQLite-safe).

    Reads existing columns via PRAGMA and only issues ADD COLUMN for those not
    present. ADD COLUMN only — never drops or rewrites data (OP #13).
    """
    for table, column, coldef in _ADDITIVE_COLUMNS:
        rows = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        existing = {r[1] for r in rows.fetchall()}
        if column not in existing:
            await conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {column} {coldef}"
            )


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session


def reset_engine_for_tests() -> None:
    """Re-create the engine pointed at the current DATABASE_URL.

    Call from a test fixture after monkeypatching `DATABASE_URL` so the new
    connection points at the test DB instead of the dev `mpower_leadgen.db`.
    """
    global engine, async_session
    engine = create_async_engine(_database_url(), future=True)
    async_session = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
