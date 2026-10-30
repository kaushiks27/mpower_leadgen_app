"""Admin-user management tests — invite, list, role gate, activate, role change."""

from __future__ import annotations

from conftest import login, make_user


async def test_rep_cannot_list_users_403(client):
    await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "rep@buloop.com", "password123")
    assert (await client.get("/api/admin/users")).status_code == 403


async def test_unauthed_list_users_401(client):
    assert (await client.get("/api/admin/users")).status_code == 401


async def test_admin_can_list_users(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    res = await client.get("/api/admin/users")
    assert res.status_code == 200
    assert any(r["email"] == "admin@buloop.com" for r in res.json())


async def test_admin_invite_creates_pending_user(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    res = await client.post(
        "/api/admin/users/invite",
        json={
            "email": "newrep@buloop.com",
            "first_name": "New",
            "last_name": "Rep",
            "role": "rep",
        },
    )
    assert res.status_code == 200
    listing = (await client.get("/api/admin/users")).json()
    invited = next(r for r in listing if r["email"] == "newrep@buloop.com")
    assert invited["pending"] is True
    assert invited["role"] == "rep"


async def test_rep_cannot_invite_403(client):
    await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "rep@buloop.com", "password123")
    res = await client.post(
        "/api/admin/users/invite",
        json={
            "email": "x@buloop.com",
            "first_name": "X",
            "last_name": "Y",
            "role": "rep",
        },
    )
    assert res.status_code == 403


async def test_invite_invalid_role_400(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    res = await client.post(
        "/api/admin/users/invite",
        json={
            "email": "x@buloop.com",
            "first_name": "X",
            "last_name": "Y",
            "role": "superuser",
        },
    )
    assert res.status_code == 400


async def test_activate_flow_sets_password_and_login(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    await client.post(
        "/api/admin/users/invite",
        json={
            "email": "newrep@buloop.com",
            "first_name": "New",
            "last_name": "Rep",
            "role": "rep",
        },
    )
    # Mint the activation token (raw only lives in the email).
    import app.db as db_mod
    from sqlalchemy import select

    from app.auth import activation
    from app.auth.orm import User

    async with db_mod.async_session() as s:
        uid = (
            await s.execute(select(User.id).where(User.email == "newrep@buloop.com"))
        ).scalar_one()
        raw, _ = await activation.issue_activation_token(s, uid)

    res = await client.post(
        "/api/admin/users/activate",
        json={"token": raw, "new_password": "setbyme123"},
    )
    assert res.status_code == 200
    # Switch identity: a fresh login as the activated user.
    await client.post("/api/auth/logout")
    assert (await login(client, "newrep@buloop.com", "setbyme123")).status_code == 200


async def test_activate_bad_token_400(client):
    res = await client.post(
        "/api/admin/users/activate",
        json={"token": "nope", "new_password": "setbyme123"},
    )
    assert res.status_code == 400


async def test_admin_change_role(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    target_id = await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "admin@buloop.com", "password123")
    res = await client.patch(
        f"/api/admin/users/{target_id}/role", json={"role": "admin"}
    )
    assert res.status_code == 200
    listing = (await client.get("/api/admin/users")).json()
    assert next(r for r in listing if r["id"] == target_id)["role"] == "admin"


async def test_admin_cannot_change_own_role(client):
    admin_id = await make_user(
        client, "admin@buloop.com", "password123", role="admin"
    )
    await login(client, "admin@buloop.com", "password123")
    res = await client.patch(
        f"/api/admin/users/{admin_id}/role", json={"role": "rep"}
    )
    assert res.status_code == 400


async def test_admin_delete_user_and_self_block(client):
    admin_id = await make_user(
        client, "admin@buloop.com", "password123", role="admin"
    )
    target_id = await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "admin@buloop.com", "password123")
    assert (await client.delete(f"/api/admin/users/{target_id}")).status_code == 200
    assert (await client.delete(f"/api/admin/users/{admin_id}")).status_code == 400
