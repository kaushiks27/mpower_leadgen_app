"""SQLAlchemy ORM for the enrichment feature — credit ceilings + usage ledger.

Per OP #11 feature tables live here. Credits are exact integers (no money math,
no floats): one Apollo match = 1 credit, one MillionVerifier check = 1 credit.
The ceiling is an admin-set per-provider monthly cap; usage is counted per UTC
calendar month (`period` = "YYYY-MM"). These two tables make spend deterministic
and auditable.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, func

from app.db.models import Base

# Providers that spend metered credits in this slice. SSOT for the ceiling UI.
METERED_PROVIDERS = ("apollo", "millionverifier")


class CreditCeiling(Base):
    __tablename__ = "credit_ceilings"

    provider = Column(String(32), primary_key=True)  # METERED_PROVIDERS
    # Monthly credit cap. 0 = no ceiling (unlimited; warn/block disabled).
    monthly_limit = Column(Integer, nullable=False, server_default="0")
    # Last period a >=80% warning email was sent, so we send it at most once
    # per provider per month ("YYYY-MM"). NULL = never warned.
    warn_sent_period = Column(String(7), nullable=True)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class CreditUsage(Base):
    __tablename__ = "credit_usage"
    __table_args__ = (
        UniqueConstraint("provider", "period", name="uq_credit_usage_provider_period"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False, index=True)
    period = Column(String(7), nullable=False)  # "YYYY-MM" (UTC)
    used = Column(Integer, nullable=False, server_default="0")
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
