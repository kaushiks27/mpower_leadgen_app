"""Pytest fixtures — each test gets an isolated temp SQLite DB (OP #13: never
touch the dev DB) and an httpx AsyncClient bound to the ASGI app.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ENV", "dev")
os.environ["EMAIL_ENABLED"] = "false"  # never hit the network in tests
# No SEED_ADMIN_EMAIL in tests by default → seed no-ops; tests create users explicitly.
os.environ.pop("SEED_ADMIN_EMAIL", None)
os.environ.pop("SEED_ADMIN_PASSWORD", None)


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    import httpx

    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")

    import app.db as db_mod

    db_mod.reset_engine_for_tests()

    from app.db import init_db

    await init_db()

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def db():
    import app.db as db_mod

    async with db_mod.async_session() as session:
        yield session


async def make_user(client, email, password, role="rep", first="Test", last="User"):
    """Helper — create an active user directly in the DB and return its id."""
    import app.db as db_mod
    from app.auth.orm import User
    from app.auth.passwords import hash_password

    async with db_mod.async_session() as session:
        u = User(
            email=email.lower(),
            password_hash=hash_password(password),
            role=role,
            first_name=first,
            last_name=last,
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u.id


async def login(client, email, password):
    return await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
