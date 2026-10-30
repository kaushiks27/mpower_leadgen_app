"""Deterministic integer credit accounting + per-provider monthly ceiling.

Exact-math rule (CLAUDE.md): every number here is an `int`. One Apollo match and
one MillionVerifier check each cost 1 credit. Usage is counted per UTC calendar
month; the ceiling blocks new spend at 100% and a one-per-month Resend warning
fires at >=80%. No floats, no LLM — the block/warn decision is reproducible.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enrichment.orm import CreditCeiling, CreditUsage

WARN_THRESHOLD_PCT = 80  # >= this % of the ceiling fires a warning email


def current_period(now: datetime | None = None) -> str:
    """UTC "YYYY-MM". `now` injectable for deterministic tests."""
    dt = now or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")


async def get_ceiling(db: AsyncSession, provider: str) -> int:
    row = await db.get(CreditCeiling, provider)
    return int(row.monthly_limit) if row else 0


async def set_ceiling(db: AsyncSession, provider: str, monthly_limit: int) -> int:
    limit = max(0, int(monthly_limit))
    row = await db.get(CreditCeiling, provider)
    if row is None:
        db.add(CreditCeiling(provider=provider, monthly_limit=limit))
    else:
        row.monthly_limit = limit
    await db.commit()
    return limit


async def get_usage(db: AsyncSession, provider: str, period: str) -> int:
    stmt = select(CreditUsage).where(
        CreditUsage.provider == provider, CreditUsage.period == period
    )
    row = (await db.execute(stmt)).scalars().first()
    return int(row.used) if row else 0


async def record_usage(
    db: AsyncSession, provider: str, period: str, amount: int = 1
) -> int:
    """Add `amount` credits to (provider, period) and return the new total."""
    amount = int(amount)
    stmt = select(CreditUsage).where(
        CreditUsage.provider == provider, CreditUsage.period == period
    )
    row = (await db.execute(stmt)).scalars().first()
    if row is None:
        row = CreditUsage(provider=provider, period=period, used=amount)
        db.add(row)
    else:
        row.used = int(row.used) + amount
    await db.commit()
    return int(row.used)


async def would_exceed(
    db: AsyncSession, provider: str, additional: int, period: str
) -> bool:
    """True if spending `additional` would push usage past the ceiling.

    A ceiling of 0 means "no limit" -> never exceeds.
    """
    limit = await get_ceiling(db, provider)
    if limit <= 0:
        return False
    used = await get_usage(db, provider, period)
    return (used + int(additional)) > limit


def usage_pct(used: int, limit: int) -> int:
    """Integer percent used (floor). 0 when there is no ceiling."""
    if limit <= 0:
        return 0
    return (int(used) * 100) // int(limit)


async def remaining(db: AsyncSession, provider: str, period: str) -> int | None:
    """Credits left this period; None when there is no ceiling."""
    limit = await get_ceiling(db, provider)
    if limit <= 0:
        return None
    return max(0, limit - await get_usage(db, provider, period))


async def should_warn(db: AsyncSession, provider: str, period: str) -> bool:
    """True if usage is >=80% of the ceiling and no warning was sent this period."""
    limit = await get_ceiling(db, provider)
    if limit <= 0:
        return False
    used = await get_usage(db, provider, period)
    if usage_pct(used, limit) < WARN_THRESHOLD_PCT:
        return False
    row = await db.get(CreditCeiling, provider)
    return not (row and row.warn_sent_period == period)


async def mark_warned(db: AsyncSession, provider: str, period: str) -> None:
    row = await db.get(CreditCeiling, provider)
    if row is not None:
        row.warn_sent_period = period
        await db.commit()
