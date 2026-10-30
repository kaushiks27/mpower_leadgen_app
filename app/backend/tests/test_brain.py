"""mPower's Brain — catalog module tests (deterministic, no network/spend).

Covers the load-bearing invariants: dedup determinism, idempotent upsert,
manual-row protection, exact-decimal price validation, advisory-band parsing,
and the admin-only API gate.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from conftest import login, make_user

from app.brain import claude_verify, service
from app.brain.models import EditRequest, ManualAddRequest


@pytest_asyncio.fixture
async def session(client):
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


# --- dedup + content hash ----------------------------------------------------
def test_dedup_key_deterministic():
    assert service.dedup_key_synced("product", "4s") == service.dedup_key_synced("product", "4s")


def test_manual_key_never_collides_with_synced():
    # A manual row named like a handle must NOT share a synced row's key.
    assert service.dedup_key_manual("product", "4s") != service.dedup_key_synced("product", "4s")


def test_content_hash_changes_with_price():
    a = service.content_hash("Pack", "100", "Survey", True)
    b = service.content_hash("Pack", "200", "Survey", True)
    assert a != b


# --- idempotent upsert + manual protection -----------------------------------
def _rows():
    return [
        {"kind": "product", "name": "4S Pack", "handle": "4s-pack",
         "category": "Survey", "price_inr": "1770", "source_url": "u"},
        {"kind": "service", "name": "Recycling", "handle": "recycle",
         "category": "Recycling", "price_inr": None, "source_url": "u"},
    ]


async def test_upsert_idempotent(session):
    i1, u1, s1 = await service.upsert_synced(session, _rows())
    assert (i1, u1, s1) == (2, 0, 0)
    i2, u2, s2 = await service.upsert_synced(session, _rows())
    assert (i2, u2, s2) == (0, 2, 0)  # 0 new, both refreshed
    items = await service.list_items(session, include_archived=True)
    assert len(items) == 2


async def test_sync_never_overwrites_manual_row(session):
    # Manually add a product, then run a sync row with the SAME natural name.
    manual = await service.add_manual(session, kind="product", name="My Custom Pack", price_inr="9999")
    assert manual.manual is True and manual.band == "Sure"
    # A synced row whose handle equals that name would key differently (salted),
    # but even a direct collision is skipped. Force the collision:
    row = {"kind": "product", "name": "My Custom Pack", "handle": None,
           "category": "X", "price_inr": "1", "source_url": "u"}
    # give it the manual dedup key so it WOULD hit the same row
    inserted, updated, skipped = await service.upsert_synced(session, [
        {**row, "handle": "My Custom Pack"},  # synced key = sha(product|my custom pack)
    ])
    # different key -> it inserts a separate synced row; the manual row is untouched
    again = await service.list_items(session, include_archived=True)
    mrow = [i for i in again if i.manual][0]
    assert mrow.price_inr == "9999"  # manual price preserved


async def test_manual_duplicate_rejected(session):
    await service.add_manual(session, kind="service", name="Dup", price_inr=None)
    with pytest.raises(ValueError):
        await service.add_manual(session, kind="service", name="Dup", price_inr=None)


async def test_price_override_locks_and_survives_resync(session):
    rows = [{"kind": "product", "name": "Pack A", "handle": "pack-a",
             "category": "Survey", "price_inr": "100", "source_url": "u"}]
    await service.upsert_synced(session, rows)
    item = (await service.list_items(session, include_archived=True))[0]
    assert bool(item.price_locked) is False
    # user overrides the price
    await service.edit_item(session, item.id, price_inr="555")
    # a later sync re-sends the ORIGINAL price — override must survive
    await service.upsert_synced(session, rows)
    again = (await service.list_items(session, include_archived=True))[0]
    assert again.price_inr == "555" and bool(again.price_locked) is True


async def test_edit_updates_price_and_archive(session):
    item = await service.add_manual(session, kind="product", name="Editable", price_inr="100")
    await service.edit_item(session, item.id, price_inr="250", archived=True)
    fresh = await service.list_items(session, include_archived=True)
    e = [i for i in fresh if i.name == "Editable"][0]
    assert e.price_inr == "250" and bool(e.archived) is True


# --- exact-decimal price validation ------------------------------------------
def test_price_validation_accepts_decimal_string():
    assert ManualAddRequest(kind="product", name="x", price_inr="45480.00").price_inr == "45480.00"


def test_price_validation_rejects_nonnumeric():
    with pytest.raises(ValueError):
        ManualAddRequest(kind="product", name="x", price_inr="abc")


def test_price_validation_rejects_negative():
    with pytest.raises(ValueError):
        EditRequest(price_inr="-5")


def test_kind_must_be_valid():
    with pytest.raises(ValueError):
        ManualAddRequest(kind="widget", name="x")


# --- advisory band parsing (never silently Sure) -----------------------------
def test_parse_valid_verdict():
    v = claude_verify.parse_verdict('{"band": "Likely", "reason": "ok", "confidence": 0.8}')
    assert v["band"] == "Likely" and v["confidence"] == "0.8"


def test_parse_junk_falls_back_to_unsure():
    v = claude_verify.parse_verdict("not json at all")
    assert v["band"] == "Unsure" and "unscored" in v["reason"]


def test_parse_invalid_band_falls_back_to_unsure():
    v = claude_verify.parse_verdict('{"band": "Maybe", "reason": "x", "confidence": 1}')
    assert v["band"] == "Unsure"


# --- admin-only API gate -----------------------------------------------------
async def test_list_requires_admin(client):
    await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "rep@buloop.com", "password123")
    assert (await client.get("/api/brain/catalog")).status_code == 403


async def test_list_unauthed_401(client):
    assert (await client.get("/api/brain/catalog")).status_code == 401


async def test_admin_can_add_and_list(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    res = await client.post(
        "/api/brain/catalog",
        json={"kind": "product", "name": "Demo Pack", "price_inr": "1234.50"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["manual"] is True and body["band"] == "Sure" and body["price_inr"] == "1234.50"
    listing = (await client.get("/api/brain/catalog")).json()
    assert any(i["name"] == "Demo Pack" for i in listing)


async def test_sync_route_rep_forbidden(client):
    # Gate-only: a rep can't even reach the launch path (no bg job, no network).
    await make_user(client, "rep@buloop.com", "password123", role="rep")
    await login(client, "rep@buloop.com", "password123")
    assert (await client.post("/api/brain/catalog/sync", json={})).status_code == 403


# --- dev reference + active-sync (read-only surfaces) ------------------------
async def test_dev_info_exposes_real_prompt(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    info = (await client.get("/api/brain/catalog/dev-info")).json()
    assert "SalesPath Sure" in info["claude_system"]  # good/bad examples present
    assert info["apify_actor"] == "apify~website-content-crawler"
    assert "products.json" in info["products_url"]
    assert "{name}" in info["claude_user_template"]


async def test_active_sync_none_when_idle(client):
    await make_user(client, "admin@buloop.com", "password123", role="admin")
    await login(client, "admin@buloop.com", "password123")
    body = (await client.get("/api/brain/catalog/active-sync")).json()
    assert body["job"] is None


async def test_seed_loads_snapshot_when_empty_and_is_idempotent(client, tmp_path, monkeypatch):
    import json

    import app.db as db_mod
    import app.brain.seed as seed_mod
    from app.brain.seed import seed_brain_catalog_if_empty

    # The real catalog snapshot is not shipped in this repo; use a small fake one.
    fake = [
        {"kind": "product", "name": f"Sample Pack {i}", "category": "Sample",
         "price_inr": "1000", "manual": False, "dedup_key": f"sample-{i}"}
        for i in range(3)
    ]
    snap = tmp_path / "catalog_snapshot.json"
    snap.write_text(json.dumps(fake), encoding="utf-8")
    monkeypatch.setattr(seed_mod, "_SNAPSHOT", snap)

    await seed_brain_catalog_if_empty()  # table empty → loads snapshot
    async with db_mod.async_session() as s:
        first = await service.list_items(s, include_archived=True)
    assert len(first) == 3  # every snapshot row loaded
    assert all(i.manual is False or i.manual == 0 for i in first)  # synced rows only

    await seed_brain_catalog_if_empty()  # non-empty now → no-op
    async with db_mod.async_session() as s:
        again = await service.list_items(s, include_archived=True)
    assert len(again) == len(first)  # never duplicates


def test_build_user_fills_template():
    class _Item:
        kind = "product"
        name = "4S Pack"
        price_inr = "1770"
        category = "Survey"
        source_url = "u"

    out = claude_verify.build_user(_Item(), "evidence here")
    assert '"4S Pack"' in out and "1770" in out and "evidence here" in out
