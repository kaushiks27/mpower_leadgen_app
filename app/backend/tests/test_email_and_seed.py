"""Email-module + first-admin-seed tests."""

from __future__ import annotations

import os

from sqlalchemy import func, select

from conftest import login


# ---- email module ----

def test_send_email_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("EMAIL_ENABLED", "false")
    from app.email import send_email

    # Returns None, never raises, never hits the network.
    assert send_email(to="x@y.com", subject="s", html="<p>h</p>", text="t") is None


def test_templates_build_invite_and_reset():
    from app.email.templates import build_invite_email, build_reset_email

    subj, html, text = build_invite_email(
        activate_url="http://x/activate?token=abc", invitee_email="a@b.com"
    )
    assert "abc" in html and "abc" in text
    assert subj and "SalesPath" in subj  # rebranded to "SalesPath by BuLoop AI" (S-10)

    subj2, html2, text2 = build_reset_email(
        reset_url="http://x/reset-password?token=zzz", recipient_email="a@b.com"
    )
    assert "zzz" in html2 and "zzz" in text2
    assert subj2


def test_brand_name_env_overrides_templates(monkeypatch):
    monkeypatch.setenv("APP_BRAND_NAME", "Acme CRM")
    from app.email.templates import build_invite_email

    subj, html, _ = build_invite_email(
        activate_url="http://x", invitee_email="a@b.com"
    )
    assert "Acme CRM" in subj and "Acme CRM" in html


# ---- first-admin seed ----

async def test_seed_with_password_creates_active_admin(client, monkeypatch):
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "admin@buloop.com")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "supersecret1")
    from app.auth.seed import seed_admin_if_missing

    await seed_admin_if_missing()
    # Active admin can log in directly.
    assert (await login(client, "admin@buloop.com", "supersecret1")).status_code == 200


async def test_seed_invite_flow_creates_pending_admin(client, monkeypatch):
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "admin@buloop.com")
    monkeypatch.delenv("SEED_ADMIN_PASSWORD", raising=False)
    from app.auth.activation import PENDING_PASSWORD_SENTINEL, is_pending
    from app.auth.orm import ActivationToken, User
    from app.auth.seed import seed_admin_if_missing
    import app.db as db_mod

    await seed_admin_if_missing()
    async with db_mod.async_session() as s:
        admin = (
            await s.execute(select(User).where(User.email == "admin@buloop.com"))
        ).scalar_one()
        assert admin.role == "admin"
        assert is_pending(admin)
        assert admin.password_hash == PENDING_PASSWORD_SENTINEL
        token_count = (
            await s.execute(
                select(func.count(ActivationToken.id)).where(
                    ActivationToken.user_id == admin.id
                )
            )
        ).scalar_one()
        assert token_count == 1


async def test_seed_idempotent_when_admin_exists(client, monkeypatch):
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "admin@buloop.com")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "supersecret1")
    from app.auth.orm import User
    from app.auth.seed import seed_admin_if_missing
    import app.db as db_mod

    await seed_admin_if_missing()
    await seed_admin_if_missing()  # second call must no-op
    async with db_mod.async_session() as s:
        count = (
            await s.execute(
                select(func.count(User.id)).where(User.email == "admin@buloop.com")
            )
        ).scalar_one()
        assert count == 1


async def test_seed_no_email_noop(client, monkeypatch):
    monkeypatch.delenv("SEED_ADMIN_EMAIL", raising=False)
    from app.auth.orm import User
    from app.auth.seed import seed_admin_if_missing
    import app.db as db_mod

    await seed_admin_if_missing()
    async with db_mod.async_session() as s:
        count = (await s.execute(select(func.count(User.id)))).scalar_one()
        assert count == 0
