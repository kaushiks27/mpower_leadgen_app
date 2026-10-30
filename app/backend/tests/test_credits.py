"""Deterministic integer credit accounting + ceiling/warn logic (no network).

Uses the `client` fixture only to stand up an isolated test DB; the credit
helpers are exercised against a fresh session.
"""

from __future__ import annotations

import pytest_asyncio

from app.enrichment import credits


@pytest_asyncio.fixture
async def session(client):
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


async def test_period_is_utc_year_month():
    from datetime import datetime, timezone

    dt = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    assert credits.current_period(dt) == "2026-06"


async def test_no_ceiling_never_exceeds(session):
    # Default ceiling is 0 (no limit) -> would_exceed always False.
    assert await credits.would_exceed(session, "apollo", 9999, "2026-06") is False
    assert await credits.remaining(session, "apollo", "2026-06") is None


async def test_usage_accumulates_and_blocks_at_ceiling(session):
    await credits.set_ceiling(session, "apollo", 3)
    assert await credits.get_usage(session, "apollo", "2026-06") == 0
    assert await credits.record_usage(session, "apollo", "2026-06", 1) == 1
    assert await credits.record_usage(session, "apollo", "2026-06", 2) == 3
    # At the ceiling: one more would exceed.
    assert await credits.would_exceed(session, "apollo", 1, "2026-06") is True
    assert await credits.remaining(session, "apollo", "2026-06") == 0


async def test_usage_pct_is_integer_floor():
    assert credits.usage_pct(0, 0) == 0  # no ceiling
    assert credits.usage_pct(3, 4) == 75
    assert credits.usage_pct(79, 100) == 79
    assert credits.usage_pct(8, 10) == 80


async def test_should_warn_once_per_period(session):
    await credits.set_ceiling(session, "millionverifier", 10)
    await credits.record_usage(session, "millionverifier", "2026-06", 8)  # 80%
    assert await credits.should_warn(session, "millionverifier", "2026-06") is True
    await credits.mark_warned(session, "millionverifier", "2026-06")
    # Already warned this period -> no second warning.
    assert await credits.should_warn(session, "millionverifier", "2026-06") is False
    # A new period resets the warning.
    await credits.record_usage(session, "millionverifier", "2026-07", 9)
    assert await credits.should_warn(session, "millionverifier", "2026-07") is True


async def test_below_threshold_does_not_warn(session):
    await credits.set_ceiling(session, "apollo", 100)
    await credits.record_usage(session, "apollo", "2026-06", 79)  # 79% < 80%
    assert await credits.should_warn(session, "apollo", "2026-06") is False
