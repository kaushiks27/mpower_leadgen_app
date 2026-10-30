"""Auth router tests — login, me, logout, name + password change, reset."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from conftest import login, make_user


async def test_login_success_sets_session_and_me(client):
    await make_user(client, "rep@buloop.com", "password123", role="rep")
    res = await login(client, "rep@buloop.com", "password123")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert "mp_session" in res.cookies or res.cookies.get("mp_session") is not None

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["signed_in"] is True
    assert body["email"] == "rep@buloop.com"
    assert body["role"] == "rep"


async def test_login_wrong_password_401(client):
    await make_user(client, "rep@buloop.com", "password123")
    res = await login(client, "rep@buloop.com", "WRONG")
    assert res.status_code == 401


async def test_login_unknown_email_401(client):
    res = await login(client, "nobody@buloop.com", "whatever12")
    assert res.status_code == 401


async def test_me_unauthed_401(client):
    res = await client.get("/api/auth/me")
    assert res.status_code == 401


async def test_logout_clears_session(client):
    await make_user(client, "rep@buloop.com", "password123")
    await login(client, "rep@buloop.com", "password123")
    out = await client.post("/api/auth/logout")
    assert out.status_code == 200
    me = await client.get("/api/auth/me")
    assert me.status_code == 401


async def test_change_name(client):
    await make_user(client, "rep@buloop.com", "password123", first="Old", last="Name")
    await login(client, "rep@buloop.com", "password123")
    res = await client.patch(
        "/api/auth/me/name", json={"first_name": "Kaushik", "last_name": "M"}
    )
    assert res.status_code == 200
    assert res.json()["first_name"] == "Kaushik"
    me = await client.get("/api/auth/me")
    assert me.json()["first_name"] == "Kaushik"


async def test_change_password_then_login_with_new(client):
    await make_user(client, "rep@buloop.com", "password123")
    await login(client, "rep@buloop.com", "password123")
    res = await client.post(
        "/api/auth/change-password",
        json={"current_password": "password123", "new_password": "newpass456"},
    )
    assert res.status_code == 200
    await client.post("/api/auth/logout")
    assert (await login(client, "rep@buloop.com", "password123")).status_code == 401
    assert (await login(client, "rep@buloop.com", "newpass456")).status_code == 200


async def test_change_password_wrong_current_400(client):
    await make_user(client, "rep@buloop.com", "password123")
    await login(client, "rep@buloop.com", "password123")
    res = await client.post(
        "/api/auth/change-password",
        json={"current_password": "nope", "new_password": "newpass456"},
    )
    assert res.status_code == 400


async def test_change_password_unauthed_401(client):
    res = await client.post(
        "/api/auth/change-password",
        json={"current_password": "a", "new_password": "newpass456"},
    )
    assert res.status_code == 401


async def test_forgot_password_always_200(client):
    await make_user(client, "rep@buloop.com", "password123")
    assert (
        await client.post("/api/auth/forgot-password", json={"email": "rep@buloop.com"})
    ).status_code == 200
    # Unknown email also 200 (no enumeration).
    assert (
        await client.post(
            "/api/auth/forgot-password", json={"email": "ghost@buloop.com"}
        )
    ).status_code == 200


async def test_reset_password_happy_path(client):
    user_id = await make_user(client, "rep@buloop.com", "password123")
    # Mint a reset token directly (raw token only ever lives in the email).
    import app.db as db_mod
    from app.auth.orm import PasswordResetToken

    raw = "reset-raw-token-xyz"
    h = hashlib.sha256(raw.encode()).hexdigest()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with db_mod.async_session() as s:
        s.add(
            PasswordResetToken(
                token_hash=h,
                user_id=user_id,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        await s.commit()

    res = await client.post(
        "/api/auth/reset-password", json={"token": raw, "new_password": "brandnew99"}
    )
    assert res.status_code == 200
    assert (await login(client, "rep@buloop.com", "brandnew99")).status_code == 200
    # Token is single-use.
    assert (
        await client.post(
            "/api/auth/reset-password",
            json={"token": raw, "new_password": "another123"},
        )
    ).status_code == 400


async def test_reset_password_bad_token_400(client):
    res = await client.post(
        "/api/auth/reset-password",
        json={"token": "does-not-exist", "new_password": "brandnew99"},
    )
    assert res.status_code == 400
