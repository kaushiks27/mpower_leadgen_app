"""API-key resolution + persistence.

Resolution order per provider (DB-wins-when-present, env fallback):
  1. DB row (decrypted, cached in-process) — set/rotated via the Settings UI.
  2. env var (bootstrap) — e.g. RESEND_API_KEY. Lets the app work before any
     key is saved, and is the fallback when an admin clears the DB key.
  3. None.

The decrypted DB keys live in a process-level cache (`_CACHE`) loaded once at
startup and updated on set/clear, so the hot path (`resolve_api_key`, used by
the synchronous email sender) never touches the DB or the crypto layer per
call. This also keeps the dependency direction clean: `email` imports nothing
from here — main.py registers `resolve_api_key("resend")` as the email key
resolver at startup (feature→infra), so `email` never imports `settings`.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings.crypto import decrypt, encrypt
from app.settings.orm import PROVIDERS, AppSecret

logger = logging.getLogger(__name__)

# provider -> bootstrap env var
ENV_VAR = {
    "apify": "APIFY_API_KEY",
    "apollo": "APOLLO_API_KEY",
    "instantly": "INSTANTLY_API_KEY",
    "resend": "RESEND_API_KEY",
    "millionverifier": "MILLIONVERIFIER_API_KEY",  # S-6 email verification
    "anthropic": "ANTHROPIC_API_KEY",  # S-7 Claude icebreaker generation
}

# In-process decrypted DB keys. provider -> plaintext. Absent = no DB row.
_CACHE: dict[str, str] = {}


def _last4(secret: str) -> str:
    return secret[-4:] if len(secret) >= 4 else secret


async def load_cache() -> None:
    """Populate `_CACHE` from the DB. Called once from FastAPI lifespan."""
    import app.db as db_mod

    _CACHE.clear()
    async with db_mod.async_session() as db:
        rows = (await db.execute(select(AppSecret))).scalars().all()
        for row in rows:
            try:
                _CACHE[row.provider] = decrypt(row.ciphertext)
            except Exception as e:  # corrupt/rotated key — skip, fall back to env
                logger.warning(
                    "settings: could not decrypt %s key (%s) — falling back to env",
                    row.provider,
                    e,
                )


def resolve_api_key(provider: str) -> str | None:
    """Sync resolver: cached DB key, else env, else None. Hot-path safe."""
    cached = _CACHE.get(provider)
    if cached:
        return cached
    env_name = ENV_VAR.get(provider)
    if env_name:
        env_val = (os.environ.get(env_name) or "").strip()
        if env_val:
            return env_val
    return None


def key_source(provider: str) -> str:
    """Where would `resolve_api_key` get this key from? db | env | none."""
    if _CACHE.get(provider):
        return "db"
    env_name = ENV_VAR.get(provider)
    if env_name and (os.environ.get(env_name) or "").strip():
        return "env"
    return "none"


def key_status(provider: str) -> dict:
    """Status dict for the UI — never the secret itself."""
    source = key_source(provider)
    if source == "db":
        last4 = _last4(_CACHE[provider])
    elif source == "env":
        env_val = (os.environ.get(ENV_VAR[provider]) or "").strip()
        last4 = _last4(env_val)
    else:
        last4 = None
    return {
        "provider": provider,
        "is_set": source != "none",
        "last4": last4,
        "source": source,
    }


def all_statuses() -> list[dict]:
    return [key_status(p) for p in PROVIDERS]


async def set_api_key(db: AsyncSession, provider: str, raw: str) -> None:
    """Encrypt + upsert a key, and update the in-process cache."""
    raw = raw.strip()
    ciphertext = encrypt(raw)
    last4 = _last4(raw)
    row = await db.get(AppSecret, provider)
    if row is None:
        db.add(AppSecret(provider=provider, ciphertext=ciphertext, last4=last4))
    else:
        row.ciphertext = ciphertext
        row.last4 = last4
    await db.commit()
    _CACHE[provider] = raw


async def clear_api_key(db: AsyncSession, provider: str) -> None:
    """Delete the DB key (reverts resolution to env). Cache evicted too."""
    row = await db.get(AppSecret, provider)
    if row is not None:
        await db.delete(row)
        await db.commit()
    _CACHE.pop(provider, None)
