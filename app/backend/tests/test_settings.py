"""Encrypted API-key settings — admin-gated, write-only, env fallback, and the
Resend env→DB migration (key never leaks in responses or storage)."""

from __future__ import annotations

import pytest

from tests.conftest import login, make_user


async def _admin(client):
    await make_user(client, "admin@x.com", "pw12345678", role="admin")
    await login(client, "admin@x.com", "pw12345678")


@pytest.fixture(autouse=True)
def _clear_key_cache(monkeypatch):
    # Module-level cache is process-global; reset it between tests for isolation.
    import app.settings.keys as keys_mod

    keys_mod._CACHE.clear()
    for env in ("APIFY_API_KEY", "APOLLO_API_KEY", "INSTANTLY_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    yield
    keys_mod._CACHE.clear()


# ---- crypto round-trip -----------------------------------------------------

def test_encrypt_decrypt_roundtrip():
    from app.settings.crypto import decrypt, encrypt

    token = encrypt("super-secret-key-1234")
    assert token != "super-secret-key-1234"  # not plaintext
    assert decrypt(token) == "super-secret-key-1234"


def test_decrypt_rejects_garbage_token():
    from app.settings.crypto import InvalidToken, decrypt

    with pytest.raises(InvalidToken):
        decrypt("not-a-valid-fernet-token")


# ---- access control --------------------------------------------------------

async def test_rep_blocked(client):
    await make_user(client, "rep@x.com", "pw12345678", role="rep")
    await login(client, "rep@x.com", "pw12345678")
    assert (await client.get("/api/settings/keys")).status_code == 403
    r = await client.put("/api/settings/keys/apify", json={"api_key": "k"})
    assert r.status_code == 403


async def test_anonymous_401(client):
    assert (await client.get("/api/settings/keys")).status_code == 401


# ---- key lifecycle ---------------------------------------------------------

async def test_list_reports_all_providers_unset(client):
    await _admin(client)
    rows = (await client.get("/api/settings/keys")).json()
    providers = {r["provider"] for r in rows}
    assert providers == {
        "apify", "apollo", "instantly", "resend", "millionverifier", "anthropic",
    }
    for r in rows:
        assert r["is_set"] is False
        assert r["source"] == "none"


async def test_set_key_masked_and_no_plaintext(client):
    await _admin(client)
    r = await client.put(
        "/api/settings/keys/apollo", json={"api_key": "APOLLO-XYZ-9876"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_set"] is True
    assert body["source"] == "db"
    assert body["last4"] == "9876"
    # secret never echoed back
    assert "APOLLO-XYZ-9876" not in r.text
    assert "api_key" not in body

    # stored ciphertext is not the plaintext
    import app.db as db_mod
    from app.settings.orm import AppSecret

    async with db_mod.async_session() as s:
        row = await s.get(AppSecret, "apollo")
        assert row is not None
        assert "APOLLO-XYZ-9876" not in row.ciphertext


async def test_rotate_then_clear_reverts_to_env(client, monkeypatch):
    await _admin(client)
    # save then rotate
    await client.put("/api/settings/keys/resend", json={"api_key": "first-key-1111"})
    r = await client.put("/api/settings/keys/resend", json={"api_key": "second-22"})
    assert r.json()["last4"] == "d-22"  # last 4 of "second-22"

    # an env bootstrap value exists for resend
    monkeypatch.setenv("RESEND_API_KEY", "env-resend-7777")
    # while a DB key is set, DB wins
    import app.settings.keys as keys_mod

    assert keys_mod.resolve_api_key("resend") == "second-22"

    # clear the DB key → reverts to env
    r = await client.delete("/api/settings/keys/resend")
    assert r.status_code == 200
    assert r.json()["source"] == "env"
    assert r.json()["last4"] == "7777"
    assert keys_mod.resolve_api_key("resend") == "env-resend-7777"


async def test_unknown_provider_rejected(client):
    await _admin(client)
    r = await client.put("/api/settings/keys/bogus", json={"api_key": "k"})
    assert r.status_code == 400


# ---- resolver: db-wins / env-fallback --------------------------------------

def test_resolve_prefers_cache_then_env(monkeypatch):
    import app.settings.keys as keys_mod

    keys_mod._CACHE.clear()
    monkeypatch.delenv("APIFY_API_KEY", raising=False)
    assert keys_mod.resolve_api_key("apify") is None
    monkeypatch.setenv("APIFY_API_KEY", "env-apify")
    assert keys_mod.resolve_api_key("apify") == "env-apify"
    keys_mod._CACHE["apify"] = "db-apify"
    assert keys_mod.resolve_api_key("apify") == "db-apify"
    keys_mod._CACHE.clear()
