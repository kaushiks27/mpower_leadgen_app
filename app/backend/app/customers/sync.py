"""Customer sync coroutine — the category-first pipeline behind "Sync Customers".

FIVE stages, each a distinct row in the progress popup (signalled via the job's
`detail` JSON `{"stage":1..5,"current":"…"}`):

  STAGE 1 — DISCOVER. Per mPower category (worldwide + India) and in TWO lanes
    (OEM drone-makers + reseller/distributor channel), Claude proposes + deterministic
    seeds drive an Apify google-search; candidates de-duped by domain and ATTRIBUTED
    to the (category, type) of the lane that found them.
  STAGE 2 — RESOLVE WEBSITE. A cheap httpx redirect-follow finds the canonical URL
    (NO Apify spend); unreachable → keep the candidate, flag it.
  STAGE 3 — CRAWL → LOCATION. One Apify profile-search + one homepage crawl per
    company → evidence; a cheap-model EXTRACT pass fills Country (+ name + category
    fallback when discovery left it blank).
  STAGE 4 — IDENTIFY TYPE. The same cached extraction writes the Type column
    (OEM / Reseller / Distributor) — no second network call.
  STAGE 5 — CLASSIFY. The strong model assigns the genuine-customer BAND last, over
    the already-enriched line; a battery manufacturer lands as "No" (a competitor).

Resume: re-clicking Sync on a PAUSED job continues stages 2→5 over the unfinished
(band-null) rows only — it never re-runs discovery (see `resume_sync_job`).

Deterministic Python owns dedup, counts, the plateau stop, ordering, and the
runaway backstop. Claude only proposes queries + extracts text fields + assigns the
advisory band — never a load-bearing number or pipeline state.
"""

from __future__ import annotations

import asyncio
import json

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.customers import (
    apify_client,
    claude_classify,
    config,
    contact_enrich,
    lanes,
    service,
    sourcing,
    webcheck,
)
from app.customers.apify_client import ApifyError, CallCounter
from app.jobs import runner
from app.jobs import service as jobs_service
from app.settings.keys import resolve_api_key

STAGE_LABELS = {
    1: "Discover",
    2: "Resolve website",
    3: "Crawl → location",
    4: "Identify type",
    5: "Classify",
    6: "Enrich contacts",
}


def _detail(stage: int, current: str = "", sources: dict | None = None) -> str:
    """Pack the popup's stage signal into the job.detail JSON column. `sources` carries
    the per-source discovered counts shown under Stage 1."""
    d: dict = {"stage": stage, "current": current}
    if sources:
        d["sources"] = sources
    return json.dumps(d)


async def _progress(
    work_db: AsyncSession, job_id: int, *, stage: int, current: str = "",
    sources: dict | None = None, **fields,
) -> None:
    await jobs_service.update_progress(
        work_db, job_id, detail=_detail(stage, current, sources), **fields
    )


async def _stop_requested(
    work_db: AsyncSession, job_id: int, *, stage: str, done: int, total: int, tasks=()
) -> str | None:
    """Cooperative stop check at a stage checkpoint. CANCEL wins over PAUSE:
      * cancelled → mark terminal (NOT resumable); the next Sync starts fresh.
      * paused    → mark resumable; partial work persists; Resume continues.
    Cancels any in-flight tasks, then returns "cancelled"/"paused" (truthy) so the
    caller returns, or None to keep going. Partial work is always already committed
    (each row commits as it finishes), so neither path loses data — and because it
    lives in the DB, a Resume works even after the laptop/server was off."""
    if runner.is_cancelled(job_id):
        for t in tasks:
            t.cancel()
        await jobs_service.mark_cancelled(
            work_db, job_id,
            message=f"Stopped by you during {stage} ({done}/{total}). Next Sync starts fresh.",
        )
        runner.clear_cancel(job_id)
        return "cancelled"
    if runner.is_paused(job_id):
        for t in tasks:
            t.cancel()
        await jobs_service.mark_paused(
            work_db, job_id,
            message=f"Paused during {stage} ({done}/{total}). Resume to continue.",
        )
        return "paused"
    return None


async def run_sync_job(work_db: AsyncSession, job_id: int, *, per_source: int = 50) -> None:
    apify = resolve_api_key("apify")
    if not apify:
        await jobs_service.mark_error(
            work_db, job_id, "Apify API key not set — add it in Settings."
        )
        return
    anthropic = resolve_api_key("anthropic")
    counter = CallCounter()

    categories = await service.mpower_categories(work_db)
    # Pre-seed dedup with what we already have → a repeat Sync brings the NEXT N new
    # companies per source, never re-feeding the same rows into the pipeline.
    known = await service.existing_domains(work_db)

    # ---- STAGE 1: adaptive discovery (Google + 6 multi-source lanes) --------
    await jobs_service.mark_running(
        work_db, job_id, total=0, message="Discovering customers worldwide…"
    )
    await _progress(work_db, job_id, stage=1, current="starting discovery", total=0)

    async def search_fn(queries: list[str]) -> list[dict]:
        return await apify_client.run_search(apify, queries, counter)

    async def lane_fn(queries: list[str]) -> list[dict]:
        """Fan the round's queries across all 6 lanes (own-domain first, marketplace
        last). One lane failing degrades to []; never sinks discovery."""
        if not config.LANES_ENABLED:
            return []
        qset = queries[: config.LANE_MAX_QUERIES_PER_ROUND]

        async def one(lane: str) -> list[dict]:
            return await apify_client.discover_lane(
                apify, lane, qset, config.LANE_REGION_DEFAULT.get(lane), counter,
                max_items=per_source,
                timeout=config.LANE_TIMEOUT.get(lane, config.LANE_TIMEOUT_DEFAULT),
            )

        ordered = [*lanes.OWN_DOMAIN_LANES, *lanes.MARKETPLACE_LANES]
        results = await asyncio.gather(*(one(l) for l in ordered), return_exceptions=True)
        out: list[dict] = []
        for r in results:
            if isinstance(r, list):
                out.extend(r)
        return out

    async def marketplace_resolve_fn(buf: list[dict]) -> list[dict]:
        """Marketplace rows (IndiaMART) carry no own-domain — resolve each unique
        company name to a canonical domain via the google-search lane (the blocklist
        drops the marketplace itself), preserving the native phone + source."""
        out: list[dict] = []
        seen_names: set[str] = set()
        for c in buf:
            nm = (c.get("name") or "").strip().lower()
            if not nm or nm in seen_names:
                continue
            seen_names.add(nm)
            try:
                res = await apify_client.run_search(
                    apify, sourcing.marketplace_resolve_query(c.get("name")), counter,
                    results_per_query=3,
                )
            except ApifyError:
                res = []
            cands = sourcing.extract_candidates(res)
            if cands:
                first = cands[0]
                merged = dict(c)
                merged["website"] = first["website"]
                merged["domain"] = first["domain"]
                merged["source_url"] = c.get("source_url") or first.get("source_url")
                out.append(merged)
        return out

    propose_fn = None
    if anthropic:
        async def propose_fn(cats, round_idx, seen):  # noqa: ANN001
            return await claude_classify.propose_queries(anthropic, cats, round_idx, seen)

    async def on_round(rnd: int, new_this: int, total: int) -> None:
        await _progress(
            work_db, job_id, stage=1, current=f"round {rnd}", total=0,
            message=f"Discovery round {rnd}: +{new_this} new, {total} companies so far…",
        )

    try:
        disc = await discovery_run(
            search_fn=search_fn, propose_fn=propose_fn, categories=categories,
            on_round=on_round, lane_fn=lane_fn, marketplace_resolve_fn=marketplace_resolve_fn,
            per_source=per_source, seen_domains=known,
        )
    except ApifyError as e:
        await jobs_service.mark_error(work_db, job_id, f"Discovery search failed: {e}")
        return

    candidates = disc["candidates"]
    source_counts = disc.get("source_counts", {})
    inserted, updated, skipped_manual = await service.upsert_discovered(work_db, candidates)
    await _progress(
        work_db, job_id, stage=1, current="discovery complete", created_count=inserted,
        sources=source_counts,
        message=f"Found {len(candidates)} NEW companies across {len(source_counts)} "
                f"source(s) over {disc['rounds']} round(s).",
    )

    # Only the unclassified (new + any unfinished) rows go through stages 2→6 — a
    # repeat Sync never re-processes already-classified companies.
    to_process = await service.customers_to_classify(work_db)
    summary_prefix = f"+{inserted} new, {skipped_manual} manual kept, "
    await enrich_and_classify(
        work_db, job_id, to_process,
        apify=apify, anthropic=anthropic, categories=categories,
        counter=counter, summary_prefix=summary_prefix,
    )


async def resume_sync_job(work_db: AsyncSession, job_id: int) -> None:
    """Resume a PAUSED sync — skip discovery, finish stages 2→5 over the unfinished
    (band-null / stale) rows only. Reuses the paused job's id. This is the fix for
    "Resume starts over": a fresh `run_sync_job` would re-run stage-1 discovery."""
    apify = resolve_api_key("apify")
    if not apify:
        await jobs_service.mark_error(
            work_db, job_id, "Apify API key not set — add it in Settings."
        )
        return
    anthropic = resolve_api_key("anthropic")
    categories = await service.mpower_categories(work_db)
    to_process = await service.customers_to_classify(work_db)
    await jobs_service.mark_running(
        work_db, job_id, total=len(to_process),
        message=f"Resuming — finishing the remaining {len(to_process)} companies…",
    )
    await enrich_and_classify(
        work_db, job_id, to_process,
        apify=apify, anthropic=anthropic, categories=categories,
        counter=CallCounter(), summary_prefix="resumed: ",
    )


async def enrich_and_classify(
    work_db: AsyncSession,
    job_id: int,
    to_process: list,
    *,
    apify: str,
    anthropic: str | None,
    categories: list[str],
    counter: CallCounter,
    summary_prefix: str = "",
) -> None:
    """Stages 2→6 for a set of customers. Reused by run_sync_job and resume_sync_job."""
    total = len(to_process)
    if total == 0:
        # No NEW companies to classify, but existing eligible rows may still need a
        # contact → run Stage 6 over them, then finish.
        contact_summary = await enrich_contacts(work_db, job_id)
        if contact_summary is None:  # paused mid-enrich
            return
        await jobs_service.mark_done(
            work_db, job_id, message=summary_prefix + f"no new companies · {contact_summary}",
        )
        return
    if not anthropic:
        await jobs_service.mark_error(
            work_db, job_id,
            "Anthropic API key not set — add it in Settings to enrich + classify customers.",
        )
        return

    runner.clear_pause(job_id)  # fresh start — drop any stale pause flag

    # ---- STAGE 2: resolve website (cheap httpx, no Apify) -------------------
    await _progress(
        work_db, job_id, stage=2, current="", total=total, processed=0,
        message=f"Resolving the correct website for {total} companies…",
    )
    wsem = asyncio.Semaphore(config.WEBRESOLVE_CONCURRENCY)
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=config.WEBRESOLVE_TIMEOUT,
        headers={"user-agent": "Mozilla/5.0 (compatible; mPowerBot/1.0)"},
    ) as wclient:
        async def resolve_one(it):
            async with wsem:
                url = it.website or f"https://{it.domain or ''}/"
                patch = await webcheck.resolve_website(url, client=wclient)
                return it.id, patch

        wtasks = [asyncio.create_task(resolve_one(it)) for it in to_process]
        done = 0
        for fut in asyncio.as_completed(wtasks):
            rid, patch = await fut
            await service.set_website(
                work_db, rid,
                website=patch["website"], domain=patch["domain"], verified=patch["reachable"],
            )
            done += 1
            if done % 5 == 0 or done == total:
                await _progress(
                    work_db, job_id, stage=2, current="", processed=done,
                    message=f"Resolved {done}/{total} websites",
                )
            if await _stop_requested(
                work_db, job_id, stage="website resolve", done=done, total=total, tasks=wtasks
            ):
                return

    by_item = {it.id: it for it in to_process}

    # ---- STAGE 3: crawl → location (Apify enrich + cheap EXTRACT pass) ------
    await _progress(
        work_db, job_id, stage=3, current="", processed=0,
        message=f"Crawling {total} sites for location + type…",
    )
    sem = asyncio.Semaphore(config.STAGE2_CONCURRENCY)

    async def enrich_one(it):
        async with sem:
            search_results: list[dict] = []
            try:
                search_results = await apify_client.run_search(
                    apify, sourcing.profile_queries(it.name, it.domain or ""),
                    counter, results_per_query=config.ENRICH_RESULTS_PER_QUERY,
                )
            except ApifyError:
                search_results = []
            pages: list[dict] = []
            if it.website:
                try:
                    pages = await apify_client.crawl_site(apify, it.website, counter)
                except ApifyError:
                    pages = []
            evidence = sourcing.evidence_text(pages, search_results)
            profile = await claude_classify.extract_profile(
                anthropic, name=it.name, domain=it.domain or "",
                evidence=evidence, categories=categories,
            )
            return it.id, evidence, profile

    evidence_by_id: dict[int, str] = {}
    profile_by_id: dict[int, dict] = {}
    tasks = [asyncio.create_task(enrich_one(it)) for it in to_process]
    done = 0
    for fut in asyncio.as_completed(tasks):
        rid, ev, profile = await fut
        evidence_by_id[rid] = ev
        profile_by_id[rid] = profile
        # Stage 3 writes LOCATION (country) (+ name + category fallback). Type waits for stage 4.
        await service.apply_enrichment(
            work_db, rid,
            name=profile.get("name"), country=profile.get("country"),
            category=profile.get("category"), write_country=True,
        )
        done += 1
        cur = by_item[rid].name if rid in by_item else ""
        if done % 3 == 0 or done == total:
            await _progress(
                work_db, job_id, stage=3, current=cur, processed=done,
                message=f"Location filled {done}/{total}",
            )
        if await _stop_requested(
            work_db, job_id, stage="crawl", done=done, total=total, tasks=tasks
        ):
            return

    # ---- STAGE 4: identify type (from the SAME cached extraction) -----------
    await _progress(
        work_db, job_id, stage=4, current="", processed=0,
        message=f"Identifying type for {total} companies…",
    )
    done = 0
    for rid, profile in profile_by_id.items():
        await service.apply_enrichment(
            work_db, rid, ctype=profile.get("ctype"), write_ctype=True,
        )
        done += 1
        if done % 10 == 0 or done == total:
            await _progress(
                work_db, job_id, stage=4, current="", processed=done,
                message=f"Type identified {done}/{total}",
            )
        if await _stop_requested(
            work_db, job_id, stage="type identification", done=done, total=total
        ):
            return

    # ---- STAGE 5: classify the BAND (strong model, over enriched line) ------
    await _progress(
        work_db, job_id, stage=5, current="", processed=0,
        message=f"Classifying {total} customers…",
    )
    csem = asyncio.Semaphore(config.STAGE2_CONCURRENCY)

    async def classify_one(rid):
        it = by_item[rid]
        prof = profile_by_id.get(rid, {})
        cat = it.category or prof.get("category")
        async with csem:
            try:
                verdict = await claude_classify.classify_band(
                    anthropic, name=it.name, domain=it.domain or "",
                    evidence=evidence_by_id.get(rid, ""),
                    category=cat, country=prof.get("country"),
                    ctype=it.ctype or prof.get("ctype"), categories=categories,
                )
            except claude_classify.ClaudeError:
                verdict = {
                    "name": None, "band": "Unsure",
                    "reason": "unscored — classifier error", "confidence": "0", "ctype": None,
                }
        return rid, verdict, service.content_hash(it.name, it.domain)

    ctasks = [asyncio.create_task(classify_one(rid)) for rid in by_item]
    done = 0
    for fut in asyncio.as_completed(ctasks):
        rid, verdict, h = await fut
        await service.apply_band(
            work_db, rid,
            band=verdict["band"], reason=verdict["reason"],
            confidence=verdict["confidence"], input_hash=h,
            name=verdict.get("name"), ctype=verdict.get("ctype"),
        )
        done += 1
        cur = by_item[rid].name if rid in by_item else ""
        if done % 3 == 0 or done == total:
            await _progress(
                work_db, job_id, stage=5, current=cur, processed=done,
                message=f"Classified {done}/{total}",
            )
        if await _stop_requested(
            work_db, job_id, stage="classification", done=done, total=total, tasks=ctasks
        ):
            return

    # ---- STAGE 6: enrich company contacts (Apollo + MillionVerifier) --------
    contact_summary = await enrich_contacts(work_db, job_id)
    if contact_summary is None:  # paused/cancelled mid-enrich
        return

    await jobs_service.mark_done(
        work_db, job_id,
        message=summary_prefix
        + f"{total} enriched + classified · {contact_summary} ({counter.calls} Apify calls).",
    )


async def enrich_contacts(work_db: AsyncSession, job_id: int) -> str | None:
    """STAGE 6 — fill a company phone + a verified email on EVERY eligible (Sure/Likely)
    customer missing one (new + existing). Apollo org-enrich → company phone; Apollo
    domain-scoped people_search + bulk_match → a work email; MillionVerifier gates it.
    Returns a one-line summary, or None if the job was paused mid-enrich. Skips cleanly
    when no Apollo key is set (phone/email simply stay blank)."""
    apollo = resolve_api_key("apollo")
    mv = resolve_api_key("millionverifier")
    if not apollo:
        return "contact enrich skipped (no Apollo key)"
    targets = await service.customers_to_enrich(work_db, limit=config.ENRICH_MAX_PER_RUN)
    total = len(targets)
    if total == 0:
        return "contacts already complete"

    await _progress(
        work_db, job_id, stage=6, current="", total=total, processed=0,
        message=f"Enriching contacts for {total} eligible customers…",
    )
    sem = asyncio.Semaphore(config.ENRICH_CONCURRENCY)

    async def enrich_one(it):
        async with sem:
            try:
                res = await contact_enrich.enrich_contact(
                    apollo, mv, domain=it.domain or "", country=it.country,
                    per_page=config.APOLLO_PEOPLE_PER_PAGE, timeout=config.ENRICH_TIMEOUT,
                )
            except Exception:  # noqa: BLE001 — one company failing never sinks the stage
                res = {"phone": None, "email": None, "email_quality": None}
            return it.id, res

    tasks = [asyncio.create_task(enrich_one(it)) for it in targets]
    done = got_email = got_phone = 0
    for fut in asyncio.as_completed(tasks):
        rid, res = await fut
        await service.set_contact(
            work_db, rid,
            phone=res.get("phone"), email=res.get("email"),
            email_quality=res.get("email_quality"),
        )
        if res.get("email"):
            got_email += 1
        if res.get("phone"):
            got_phone += 1
        done += 1
        if done % 3 == 0 or done == total:
            await _progress(
                work_db, job_id, stage=6, current="", processed=done,
                message=f"Contacts {done}/{total} · +{got_email} email, +{got_phone} phone",
            )
        if await _stop_requested(
            work_db, job_id, stage="contact enrich", done=done, total=total, tasks=tasks
        ):
            return None  # job already marked paused/cancelled
    return f"+{got_email} email, +{got_phone} phone on {total} eligible"


async def discovery_run(
    *, search_fn, propose_fn, categories, on_round,
    lane_fn=None, marketplace_resolve_fn=None, per_source=None, seen_domains=None,
):
    """Thin wrapper that injects the config caps into the pure discovery loop."""
    from app.customers import discovery

    return await discovery.run_discovery(
        search_fn=search_fn,
        propose_fn=propose_fn,
        categories=categories,
        max_rounds=config.MAX_DISCOVERY_ROUNDS,
        plateau_threshold=config.PLATEAU_THRESHOLD,
        max_queries_per_round=config.MAX_QUERIES_PER_ROUND,
        max_candidates=config.MAX_CANDIDATES,
        on_round=on_round,
        lane_fn=lane_fn,
        marketplace_resolve_fn=marketplace_resolve_fn,
        per_source_cap=per_source,
        seen_domains=seen_domains,
    )
