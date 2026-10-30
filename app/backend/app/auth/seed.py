"""Idempotent first-admin seed.

Reads `SEED_ADMIN_EMAIL` (required) + optional `SEED_ADMIN_PASSWORD` on boot.
If no admin exists yet:
  - With `SEED_ADMIN_PASSWORD` set → create an ACTIVE admin (break-glass login).
  - Without it → create a PENDING admin, issue an activation token, and email
    a real invite (set-password link). The activation URL is also logged so
    the admin can always get in even if email delivery is delayed.

Runs once-effectively: subsequent boots see an existing admin and no-op.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import func, select

from app.auth.activation import (
    PENDING_PASSWORD_SENTINEL,
    invalidate_open_tokens,
    issue_activation_token,
)
from app.auth.orm import User
from app.auth.passwords import hash_password
from app.email import EmailDeliveryError, send_email
from app.email.templates import build_invite_email

logger = logging.getLogger(__name__)


async def seed_admin_if_missing() -> None:
    # Re-import so test fixtures that swap the engine are honored.
    import app.db as db_mod

    email = (os.environ.get("SEED_ADMIN_EMAIL") or "").strip().lower()
    if not email:
        logger.info("seed_admin: SEED_ADMIN_EMAIL not set, skipping")
        return

    password = os.environ.get("SEED_ADMIN_PASSWORD") or ""

    async with db_mod.async_session() as db:
        admin_count = (
            await db.execute(select(func.count(User.id)).where(User.role == "admin"))
        ).scalar_one()
        if admin_count > 0:
            return

        existing = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if password:
            # Break-glass: create/promote an active admin with a known password.
            if existing is not None:
                existing.role = "admin"
                existing.password_hash = hash_password(password)
                await db.commit()
                logger.info("seed_admin: promoted %s to active admin", email)
                return
            db.add(
                User(
                    email=email,
                    password_hash=hash_password(password),
                    role="admin",
                    first_name="Admin",
                    last_name="User",
                )
            )
            await db.commit()
            logger.info("seed_admin: created active admin %s", email)
            return

        # Invite flow — create a PENDING admin + email a set-password link.
        if existing is not None:
            existing.role = "admin"
            existing.password_hash = PENDING_PASSWORD_SENTINEL
            user = existing
        else:
            user = User(
                email=email,
                password_hash=PENDING_PASSWORD_SENTINEL,
                role="admin",
                first_name="Admin",
                last_name="User",
            )
            db.add(user)
        await db.commit()
        await db.refresh(user)

        await invalidate_open_tokens(db, user.id)
        raw_token, _ = await issue_activation_token(db, user.id)
        base_url = os.environ.get("APP_BASE_URL", "http://localhost:3030").rstrip("/")
        activate_url = f"{base_url}/activate?token={raw_token}"
        logger.warning("[seed_admin] activation link for %s: %s", email, activate_url)

        subject, html, text = build_invite_email(
            activate_url=activate_url, invitee_email=email
        )
        try:
            send_email(to=email, subject=subject, html=html, text=text)
            logger.info("seed_admin: invite emailed to %s", email)
        except EmailDeliveryError as e:
            logger.warning(
                "seed_admin: invite email failed for %s (%s) — use the logged "
                "activation link above",
                email,
                e,
            )
