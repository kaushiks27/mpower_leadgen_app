"""Background-job infra — service transitions, runner error-handling, router."""

from __future__ import annotations

import pytest_asyncio

from app.jobs import runner
from app.jobs import service as jobs_service
from tests.conftest import login, make_user


@pytest_asyncio.fixture
async def session(client):
    import app.db as db_mod

    async with db_mod.async_session() as s:
        yield s


async def test_lifecycle_transitions(session):
    job = await jobs_service.create_job(session, kind="apollo_enrich", campaign_id=7)
    assert job.status == "pending"

    await jobs_service.mark_running(session, job.id, total=5, message="go")
    await jobs_service.update_progress(
        session, job.id, processed=2, created_count=1, credits_used=2
    )
    await jobs_service.mark_done(session, job.id, message="done")

    fresh = await jobs_service.get_job(session, job.id)
    assert fresh.status == "done"
    assert fresh.total == 5 and fresh.processed == 2
    assert fresh.created_count == 1 and fresh.credits_used == 2


async def test_latest_and_active_job(session):
    j1 = await jobs_service.create_job(session, kind="generate_leads", campaign_id=9)
    await jobs_service.mark_done(session, j1.id)
    j2 = await jobs_service.create_job(session, kind="generate_leads", campaign_id=9)

    latest = await jobs_service.latest_job(session, campaign_id=9, kind="generate_leads")
    assert latest.id == j2.id
    active = await jobs_service.active_job(session, campaign_id=9, kind="generate_leads")
    assert active.id == j2.id  # j2 still pending
    # A different kind has no job.
    assert await jobs_service.active_job(session, campaign_id=9, kind="apollo_enrich") is None


async def test_runner_marks_error_on_exception(session):
    job = await jobs_service.create_job(session, kind="apollo_enrich", campaign_id=1)

    async def boom(db, job_id):
        raise RuntimeError("kaboom")

    await runner.run_now(job.id, boom)

    import app.db as db_mod

    async with db_mod.async_session() as s2:
        fresh = await jobs_service.get_job(s2, job.id)
        assert fresh.status == "error"
        assert "kaboom" in (fresh.message or "")


async def test_runner_runs_work_to_completion(session):
    job = await jobs_service.create_job(session, kind="apollo_enrich", campaign_id=1)

    async def work(db, job_id):
        await jobs_service.mark_running(db, job_id, total=1)
        await jobs_service.mark_done(db, job_id, message="ok")

    await runner.run_now(job.id, work)
    import app.db as db_mod

    async with db_mod.async_session() as s2:
        fresh = await jobs_service.get_job(s2, job.id)
        assert fresh.status == "done"


async def test_job_router_requires_auth_and_returns_snapshot(client):
    # Unauthenticated -> 401.
    assert (await client.get("/api/jobs/1")).status_code == 401

    await make_user(client, "u@x.com", "pw12345678", role="rep")
    await login(client, "u@x.com", "pw12345678")

    import app.db as db_mod

    async with db_mod.async_session() as s:
        job = await jobs_service.create_job(s, kind="apollo_enrich", campaign_id=3)
        jid = job.id

    r = await client.get(f"/api/jobs/{jid}")
    assert r.status_code == 200
    assert r.json()["kind"] == "apollo_enrich"

    # latest-by-kind endpoint.
    r2 = await client.get("/api/jobs?campaign_id=3&kind=apollo_enrich")
    assert r2.status_code == 200 and r2.json()["id"] == jid
    # unknown kind -> 400.
    assert (await client.get("/api/jobs?campaign_id=3&kind=nope")).status_code == 400
    # missing job -> 404.
    assert (await client.get("/api/jobs/999999")).status_code == 404
