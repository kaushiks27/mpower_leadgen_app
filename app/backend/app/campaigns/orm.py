"""SQLAlchemy ORM for the campaigns feature.

Per OP #11 feature tables live here — never in `app/db/models.py`. Registered on
the shared `Base.metadata` via `app/db/__init__.py:init_db`.

Tables:
  - `campaigns`            — header (name + catalog refs + tz + send window + status)
  - `campaign_steps`       — one row per email in the sequence (FK → campaigns)
  - `campaign_roles`       — S-5b: per-campaign decision-maker role selection
  - `campaign_icp_filters` — S-5b: per-campaign ICP segment selection
both link a campaign to `catalog_items` rows (kinds `role` / `icp_filter`).

Catalog references are stored as plain integer ids with a string FK to
`catalog_items.id` (no Python import of config's ORM class — config.orm is
imported by init_db, so the table exists in metadata at DDL time). Soft-archive
only (OP: no lost data); nothing is ever hard-deleted.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.db.models import Base

# Campaign lifecycle status. Single source of truth — router imports this.
CAMPAIGN_STATUSES = ("draft", "active")

# Allowed send-window weekdays (lowercase 3-letter). Order is canonical.
SEND_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(160), nullable=False)

    # S-7: free-text campaign owner (a person's name; not a user FK for v1).
    # Surfaces as the "Campaign Owner" column on the master lead list and as a
    # pipeline-board filter. Nullable = unassigned.
    owner = Column(String(120), nullable=True)

    # Catalog references (config.catalog_items). Stored as ids; validated +
    # label-resolved in the router (one-way read of the config module).
    category_id = Column(
        Integer, ForeignKey("catalog_items.id"), nullable=False
    )
    target_category_id = Column(
        Integer, ForeignKey("catalog_items.id"), nullable=False
    )
    geography_id = Column(
        Integer, ForeignKey("catalog_items.id"), nullable=False
    )

    # S-5: how many leads this campaign wants. 0 = no target (Generate always
    # available). The Generate-Leads button stays active until the campaign's
    # non-archived lead count reaches this number. Integer count, never money.
    target_lead_count = Column(Integer, nullable=False, server_default="0", default=0)

    timezone = Column(String(64), nullable=False)  # IANA, validated via zoneinfo

    # Optional send window. send_days = CSV of SEND_DAYS; hours are 0..23 ints.
    send_days = Column(String(64), nullable=False, server_default="mon,tue,wed,thu,fri")
    send_start_hour = Column(Integer, nullable=False, server_default="9")
    send_end_hour = Column(Integer, nullable=False, server_default="17")

    status = Column(String(16), nullable=False, server_default="draft", default="draft")

    # 08062026_cr CR-2/Q9: per-campaign "require icebreaker" toggle. Drives the
    # Add-Leads picker eligibility + the Instantly push gate. Default True
    # preserves the prior verified+icebroken send discipline.
    require_icebreaker = Column(
        Boolean, nullable=False, server_default="1", default=True
    )

    archived = Column(Boolean, nullable=False, server_default="0", default=False)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    steps = relationship(
        "CampaignStep",
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="CampaignStep.step_order",
    )
    # S-5b targeting selections. Ordered by catalog_item_id for determinism.
    role_links = relationship(
        "CampaignRole",
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="CampaignRole.catalog_item_id",
    )
    icp_links = relationship(
        "CampaignIcpFilter",
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="CampaignIcpFilter.catalog_item_id",
    )


class CampaignStep(Base):
    __tablename__ = "campaign_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(
        Integer, ForeignKey("campaigns.id"), nullable=False, index=True
    )
    step_order = Column(Integer, nullable=False)  # 1-based, deterministic order
    wait_days = Column(Integer, nullable=False, server_default="0")  # before step
    subject = Column(String(300), nullable=False)
    body = Column(Text, nullable=False)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    campaign = relationship("Campaign", back_populates="steps")


class CampaignRole(Base):
    """One selected decision-maker role for a campaign (S-5b).

    `catalog_item_id` references a `catalog_items` row of kind `role`. Stored as
    a plain int FK (no Python import of config's ORM class — one-way boundary).
    """

    __tablename__ = "campaign_roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(
        Integer, ForeignKey("campaigns.id"), nullable=False, index=True
    )
    catalog_item_id = Column(
        Integer, ForeignKey("catalog_items.id"), nullable=False
    )

    campaign = relationship("Campaign", back_populates="role_links")


class CampaignIcpFilter(Base):
    """One selected ICP-segment filter for a campaign (S-5b).

    `catalog_item_id` references a `catalog_items` row of kind `icp_filter`.
    """

    __tablename__ = "campaign_icp_filters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(
        Integer, ForeignKey("campaigns.id"), nullable=False, index=True
    )
    catalog_item_id = Column(
        Integer, ForeignKey("catalog_items.id"), nullable=False
    )

    campaign = relationship("Campaign", back_populates="icp_links")
