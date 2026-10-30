"""SQLAlchemy ORM for the settings feature — encrypted API keys at rest.

Per OP #11, lives here — never in `app/db/models.py`. One row per provider.
`ciphertext` holds the Fernet-encrypted key (never plaintext); `last4` is the
clear last-4 chars for a masked confirm in the UI. Plaintext is never stored.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, String, func

from app.db.models import Base

# Providers whose keys we hold. Single source of truth — keys.py + router import.
# millionverifier added at S-6 (email verification); anthropic added at S-7
# (Claude icebreaker generation). No migration needed — app_secrets is keyed by
# the provider string.
PROVIDERS = (
    "apify",
    "apollo",
    "instantly",
    "resend",
    "millionverifier",
    "anthropic",
)


class AppSecret(Base):
    __tablename__ = "app_secrets"

    provider = Column(String(32), primary_key=True)
    ciphertext = Column(String(512), nullable=False)
    last4 = Column(String(4), nullable=False, server_default="")
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
