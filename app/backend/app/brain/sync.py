"""Catalog sync coroutine — the background-job work for "Sync Products & Services".

Pipeline (Apify-first + Claude verify line-by-line, per the user-agreed strategy):
  1. Apify crawl mpowerlithium.com (evidence + service pages).
  2. GET Shopify products.json (authoritative product rows).
  3. Idempotent upsert into the master table — MANUAL ROWS PROTECTED.
  4. Claude verifies each non-manual changed/new row line-by-line -> data-confidence
     band. Verify calls run concurrently (network only); DB writes stay serial.

Deterministic Python owns counts, dedup, idempotency. Claude only assigns the
advisory band. Re-syncs are cheap: a row is re-verified only if its content
changed (content_hash).
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.brain import apify_client, claude_verify, service, sourcing
from app.jobs import service as jobs_service
from app.settings.keys import resolve_api_key

_VERIFY_CONCURRENCY = 8


async def run_sync_job(work_db: AsyncSession, job_id: int) -> None:
    apify = resolve_api_key("apify")
    if not apify:
        await jobs_service.mark_error(
            work_db, job_id, "Apify API key not set — add it in Settings."
        )
        return
    anthropic = resolve_api_key("anthropic")

    await jobs_service.mark_running(
        work_db, job_id, total=0, message="Crawling mpowerlithium.com…"
    )

    # 1 + 2. gather sources
    try:
        pages = await apify_client.crawl_site(apify, sourcing.MPOWER_HOME)
    except apify_client.ApifyError as e:
        await jobs_service.mark_error(work_db, job_id, f"Apify crawl failed: {e}")
        return
    try:
        products = await sourcing.fetch_products()
    except Exception as e:  # noqa: BLE001 — surface a clean job error
        await jobs_service.mark_error(
            work_db, job_id, f"Could not fetch products.json: {e}"
        )
        return
    services = sourcing.services_from_crawl(pages)

    # 3. idempotent upsert (manual protected)
    inserted, updated, skipped_manual = await service.upsert_synced(
        work_db, products + services
    )
    await jobs_service.update_progress(
        work_db, job_id, created_count=inserted,
        message=f"Stored {inserted} new / {updated} updated. Matching evidence…",
    )

    # 4. evidence per non-manual row + which need (re)verification
    all_items = await service.list_items(work_db, include_archived=False)
    evidence_by_id = {
        it.id: sourcing.evidence_for(it.name, it.handle, pages)
        for it in all_items if not it.manual
    }
    to_verify = await service.items_to_verify(work_db, evidence_by_id)
    total = len(to_verify)

    await jobs_service.update_progress(
        work_db, job_id, total=total, processed=0,
        message=f"Verifying {total} rows with Claude…" if total else
                "Catalog already up to date — nothing to verify.",
    )
    if total == 0:
        await jobs_service.mark_done(
            work_db, job_id,
            message=f"Sync complete: +{inserted} new, {updated} updated, "
                    f"{skipped_manual} manual kept. No rows needed re-verifying.",
        )
        return
    if not anthropic:
        await jobs_service.mark_error(
            work_db, job_id,
            "Anthropic API key not set — add it in Settings to verify rows.",
        )
        return

    # Concurrent verify (network only); collect verdicts; DB writes stay serial.
    sem = asyncio.Semaphore(_VERIFY_CONCURRENCY)

    async def verify_one(it):
        ev = evidence_by_id.get(it.id, "")
        async with sem:
            try:
                verdict = await claude_verify.verify_item(anthropic, it, ev)
            except claude_verify.ClaudeError:
                verdict = {
                    "band": "Unsure",
                    "reason": "unscored — verifier error",
                    "confidence": "0",
                }
        return it.id, verdict, service.content_hash(
            it.name, it.price_inr, it.category, bool(ev)
        )

    tasks = [asyncio.create_task(verify_one(it)) for it in to_verify]
    verdicts = []
    done = 0
    for fut in asyncio.as_completed(tasks):
        rid, verdict, h = await fut
        verdicts.append((rid, verdict, h))
        done += 1
        if done % 5 == 0 or done == total:
            await jobs_service.update_progress(
                work_db, job_id, processed=done, message=f"Verified {done}/{total}"
            )

    # 5. write bands serially (deterministic; single-writer)
    for rid, verdict, h in verdicts:
        await service.apply_band(
            work_db, rid,
            band=verdict["band"], reason=verdict["reason"],
            confidence=verdict["confidence"], input_hash=h,
        )

    await jobs_service.mark_done(
        work_db, job_id,
        message=f"Sync complete: +{inserted} new, {updated} updated, "
                f"{skipped_manual} manual kept, {total} verified.",
    )
