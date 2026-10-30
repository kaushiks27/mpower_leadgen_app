"""Generate-Leads orchestration — the staged worker behind "Generate Leads".

Finds DECISION-MAKER people inside mPower's existing prospective-customer companies
and turns them into leads. SIX stages, signalled to the popup via the Job's
`detail` JSON ({"stage":1..6,"current":<company>,"customer_index","customer_total"}):

  1 LinkedIn discover — the LINKEDIN_ACTOR people search (titles = expand_roles).
  2 Fallback actors   — run each fallback actor, merge people.
  3 Claude widen      — if stage-1 LinkedIn hits < WIDEN_THRESHOLD, Claude proposes
                        EXTRA titles (advisory) → re-run LinkedIn once, merge.
  4 Dedup → Leads     — map_person → dedup_key → skip dupes (DB + in-batch) →
                        get-or-create Company → create Lead + a `created` LeadEvent.
  5 Apollo enrich     — match_person on the new leads → email/phone/title/enriched_at.
  6 Verify emails     — MillionVerifier → email_status/email_checked_at.

Customers are processed ONE BY ONE; between customers the worker checks the pause
flag and, if set, persists state + marks the job paused (resume continues over the
customers still "pending"). All Apify/Apollo/MV/Claude calls go through INJECTED
callables (default = live clients) so tests use fakes — no network in tests.

Determinism / exact-math: every counter + credit is an int; the LLM only proposes
advisory search terms — it never writes a stored field or a pipeline decision.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.customers.orm import CustomerItem
from app.enrichment import credits
from app.enrichment.apollo_client import ApolloError, match_person
from app.enrichment.verify_client import (
    OFF_DOMAIN,
    UNKNOWN,
    VerifyError,
    verify_email,
)
from app.jobs import runner
from app.jobs import service as jobs_service
from app.leadgen import (
    apify_client, apollo_native, config, lists, membership, roles, sourcing, widen,
)
from app.leadgen.apify_client import ApifyError, CallCounter
from app.leadgen.apollo_native import ApolloNativeError
from app.leadgen.models import DevInfo, GenerateRequest
from app.leadgen.orm import LeadgenRun
from app.leads.dedup import dedup_key
from app.leads.orm import Company, Lead, LeadEvent
from app.suppression.normalize import normalize_email
from app.settings.keys import resolve_api_key

JOB_KIND = "generate_leads"

# Apollo bulk_match enriches this many leads per call; we commit + report progress
# after each batch so the modal counter ticks (10/50, 20/50…) instead of 0/50.
_ENRICH_BATCH = 10

# Injectable signatures (default = live clients). Network I/O is injected so the
# whole flow is unit-tested with fakes — no live call, no credits spent in tests.
# Stage 0: (company, country, category) → {domain, website, linkedin_url}.
AnchorFn = Callable[[str, str | None, str | None], Awaitable[dict]]
# A discovery engine: a per-customer context dict → raw people records.
EngineFn = Callable[[dict], Awaitable[list[dict]]]
# Advisory company-name aliases for the membership gate (company → [aliases]).
AliasFn = Callable[[str], Awaitable[list[str]]]
# Takes the EXACT saturated actor-input query → returns a widened title list.
WidenFn = Callable[[dict], Awaitable[list[str]]]
Matcher = Callable[[dict], Awaitable[dict]]
Verifier = Callable[[str], Awaitable[str]]


# --- read-side service surface ----------------------------------------------
async def assemble_lists(db: AsyncSession) -> dict:
    return await lists.assemble(db)


async def get_filtered_customers(
    db: AsyncSession,
    categories_sel: list[str] | None,
    types_sel: list[str] | None,
    country: str | None,
    bands_sel: list[str] | None = None,
):
    return await lists.filtered_customers(
        db, categories_sel, types_sel, country, bands_sel
    )


def get_roles():
    return lists.role_groups()


def dev_info() -> DevInfo:
    sample = sourcing.build_linkedin_input(
        "<Customer Co>", roles.expand_roles(["Procurement & Sourcing"])[:5], "India"
    )
    return DevInfo(
        linkedin_actor=config.LINKEDIN_ACTOR,
        fallback_actors=list(config.FALLBACK_ACTORS),
        widen_model=config.WIDEN_MODEL,
        sample_actor_input=sample,
        widen_system=widen.SYSTEM,
        widen_user_template=widen.USER_TEMPLATE,
        pipeline_steps=[f"{n}. {label}" for n, label in sorted(config.STAGE_LABELS.items())],
    )


# --- run lifecycle ----------------------------------------------------------
def _detail(
    stage: int, current: str, idx: int, total: int, counts: dict | None = None
) -> str:
    d = {"stage": stage, "current": current, "customer_index": idx, "customer_total": total}
    if counts is not None:
        # Cumulative per-stage tallies across all customers processed so far, so
        # each stage row in the modal shows its own m/N rather than the (shared,
        # misleading) customer count. Display-only — not load-bearing.
        d["stage_counts"] = counts
    return json.dumps(d)


def _detail_widen(current: str, idx: int, total: int, earlier_input: dict, cid: int) -> str:
    """Stage-3 detail signalling the popup to ask the user to confirm widening."""
    return json.dumps(
        {
            "stage": 3,
            "current": current,
            "customer_index": idx,
            "customer_total": total,
            "awaiting_widen": True,
            "awaiting_cid": int(cid),
            "earlier_query": json.dumps(earlier_input, indent=2, sort_keys=True),
        }
    )


async def _get_run(db: AsyncSession, job_id: int) -> LeadgenRun | None:
    stmt = select(LeadgenRun).where(LeadgenRun.job_id == job_id).order_by(LeadgenRun.id.desc())
    return (await db.execute(stmt)).scalars().first()


async def _save_states(db: AsyncSession, run: LeadgenRun, states: dict[str, str]) -> None:
    run.customer_states_json = json.dumps(states, sort_keys=True)
    await db.commit()


async def _save_widen_states(db: AsyncSession, run: LeadgenRun, wstates: dict[str, str]) -> None:
    run.widen_states_json = json.dumps(wstates, sort_keys=True)
    await db.commit()


async def set_widen_decision(db: AsyncSession, job_id: int, *, approve: bool) -> int | None:
    """Record the user's widen choice for the company the run is paused on.

    Reads the awaiting customer id from the paused job's detail, stores
    "approved"/"skipped" against it, and returns that customer id (or None if the
    job is not actually awaiting a widen decision).
    """
    job = await jobs_service.get_job(db, job_id)
    if job is None or not job.detail:
        return None
    try:
        detail = json.loads(job.detail)
    except (ValueError, TypeError):
        return None
    if not (isinstance(detail, dict) and detail.get("awaiting_widen")):
        return None
    cid = detail.get("awaiting_cid")
    if cid is None:
        return None
    run = await _get_run(db, job_id)
    if run is None:
        return None
    wstates: dict[str, str] = json.loads(run.widen_states_json or "{}")
    wstates[str(int(cid))] = "approved" if approve else "skipped"
    await _save_widen_states(db, run, wstates)
    return int(cid)


async def cancel_run(db: AsyncSession, *, runner) -> int | None:  # noqa: ANN001
    """Permanently cancel the in-flight / paused / orphaned generate_leads run so
    the next click starts FRESH (not a resume).

    Flags a live worker to bail at its next per-customer checkpoint AND marks the
    job terminal now (status=done, non-resumable). Cancellation is cooperative at
    customer granularity — the customer currently in flight finishes (idempotent),
    nothing new is started. Returns the cancelled job id, or None if none active.
    """
    job = await jobs_service.latest_resumable(db, campaign_id=None, kind=JOB_KIND)
    if job is None:
        return None
    runner.request_cancel(job.id)
    runner.request_pause(job.id)  # nudge a live worker toward its checkpoint
    await jobs_service.mark_done(db, job.id, message="Run cancelled by user.")
    return job.id


def resume_run(
    job_id: int,
    *,
    runner,  # noqa: ANN001
    anchor: AnchorFn | None = None,
    engines: list | None = None,
    aliaser: AliasFn | None = None,
    widener: WidenFn | None = None,
    matcher: Matcher | None = None,
    verifier: Verifier | None = None,
) -> None:
    """Relaunch the staged worker for a paused job (e.g. after a widen decision)."""
    if runner.is_live(job_id):
        return
    runner.clear_pause(job_id)

    async def _resume(work_db: AsyncSession, jid: int) -> None:
        await run_generate_job(
            work_db, jid,
            anchor=anchor, engines=engines, aliaser=aliaser, widener=widener,
            matcher=matcher, verifier=verifier,
        )

    runner.launch(job_id, _resume)


async def start_run(
    db: AsyncSession,
    req: GenerateRequest,
    *,
    runner,  # noqa: ANN001 — the jobs.runner module (injected for tests)
    anchor: AnchorFn | None = None,
    engines: list | None = None,
    aliaser: AliasFn | None = None,
    widener: WidenFn | None = None,
    matcher: Matcher | None = None,
    verifier: Verifier | None = None,
):
    """Create the Job + LeadgenRun and launch the staged worker.

    Dedupe / resume: a GENUINELY live generate_leads job → return it. A PAUSED or
    ORPHANED run → RESUME it (process the customers still "pending"). Otherwise a
    fresh run over req.customer_ids.
    """
    live = await jobs_service.active_job(db, campaign_id=None, kind=JOB_KIND)
    if live is not None and runner.is_live(live.id):
        return live

    resumable = await jobs_service.latest_resumable(db, campaign_id=None, kind=JOB_KIND)
    if resumable is not None and not runner.is_live(resumable.id):
        runner.clear_pause(resumable.id)

        async def _resume(work_db: AsyncSession, job_id: int) -> None:
            await run_generate_job(
                work_db, job_id,
                anchor=anchor, engines=engines, aliaser=aliaser, widener=widener,
                matcher=matcher, verifier=verifier,
            )

        runner.launch(resumable.id, _resume)
        return resumable

    job = await jobs_service.create_job(
        db, kind=JOB_KIND, campaign_id=None, message="Queued…"
    )
    states = {str(cid): "pending" for cid in req.customer_ids}
    run = LeadgenRun(
        job_id=job.id,
        params_json=json.dumps(req.model_dump(), sort_keys=True),
        customer_states_json=json.dumps(states, sort_keys=True),
    )
    db.add(run)
    await db.commit()

    async def _work(work_db: AsyncSession, job_id: int) -> None:
        await run_generate_job(
            work_db, job_id,
            anchor=anchor, engines=engines, aliaser=aliaser, widener=widener,
            matcher=matcher, verifier=verifier,
        )

    runner.launch(job.id, _work)
    return job


# --- default live injectables -----------------------------------------------
def _default_anchor(apify: str, apollo: str | None, counter: CallCounter) -> AnchorFn:
    """Resolve {domain, website, linkedin_url}. Apollo org-enrich FIRST (gives a
    reliable domain + LinkedIn company URL, e.g. when Google can't — the Garuda
    gap), then a Google SERP scrape fills any blank it left."""
    async def _a(company: str, country: str | None, category: str | None) -> dict:
        # Google SERP runs first to discover the website domain, THEN Apollo
        # org-enrich refines the LinkedIn URL + canonical domain off that domain
        # (org-enrich is keyed by domain, so it needs the SERP domain first).
        queries = sourcing.search_queries(company, country, category)
        try:
            results = await apify_client.run_company_search(apify, queries, counter)
            picked = sourcing.pick_anchor(results)
        except ApifyError:
            picked = {"domain": "", "website": "", "linkedin_url": ""}
        domain = picked.get("domain") or ""
        website = picked.get("website") or ""
        linkedin_url = picked.get("linkedin_url") or ""
        if apollo and domain:
            try:
                org = await apollo_native.org_enrich(apollo, domain)
            except ApolloNativeError:
                org = {}
            domain = membership.registrable(org.get("domain")) or domain
            linkedin_url = linkedin_url or (org.get("linkedin_url") or "")
        return {"domain": domain, "website": website, "linkedin_url": linkedin_url}
    return _a


def _default_engines(apify: str, apollo: str | None, counter: CallCounter) -> list:
    """The ordered live discovery engines (each: ctx → raw people). ALL run + merge
    (user: every engine equal). Apollo-native FREE people-search is added as a peer;
    the snipercoder email-finder replaces the retired website crawler (engine 4)."""
    async def apollo_search(ctx: dict) -> list[dict]:
        if not apollo:
            return []
        try:
            return await apollo_native.people_search(
                apollo, ctx["domain"], ctx["titles"], ctx["country"],
                config.APOLLO_SEARCH_PER_PAGE,
            )
        except ApolloNativeError:
            return []

    async def code_crafter(ctx: dict) -> list[dict]:
        return await apify_client.run_apollo_search(
            apify, ctx["company"], ctx["domain"], ctx["titles"], ctx["country"], counter
        )

    async def li_company(ctx: dict) -> list[dict]:
        target = ctx["linkedin_url"] or ctx["company"]
        return await apify_client.run_company_employees(apify, target, ctx["titles"], counter)

    async def li_profile(ctx: dict) -> list[dict]:
        return await apify_client.run_linkedin_search(
            apify, ctx["company"], ctx["titles"], ctx["country"], counter,
            li_url=ctx.get("linkedin_url") or None,
        )

    async def email_finder(ctx: dict) -> list[dict]:
        if not ctx.get("domain"):
            return []
        out: list[dict] = []
        for cat in ctx.get("sniper_categories") or []:
            out.extend(await apify_client.run_email_finder(apify, ctx["domain"], cat, counter))
        return out

    return [("apollo", apollo_search), ("code_crafter", code_crafter),
            ("li_company", li_company), ("li_profile", li_profile),
            ("email_finder", email_finder)]


# Bulk Apollo enrich: list of identity hints → list of match dicts ALIGNED 1:1.
BulkMatcher = Callable[[list[dict]], Awaitable[list[dict]]]


def _default_bulk_matcher(apollo: str) -> BulkMatcher:
    async def _bm(hints: list[dict]) -> list[dict]:
        return await apollo_native.bulk_match(apollo, hints)
    return _bm


def _default_aliaser(anthropic: str) -> AliasFn:
    async def _al(company: str) -> list[str]:
        return await widen.propose_aliases(anthropic, company)
    return _al


def _default_widener(anthropic: str) -> WidenFn:
    async def _w(earlier_input: dict) -> list[str]:
        return await widen.propose_widen_query(anthropic, earlier_input)
    return _w


def _default_matcher(apollo: str) -> Matcher:
    async def _m(hint: dict) -> dict:
        return await match_person(apollo, hint)
    return _m


def _default_verifier(mv: str) -> Verifier:
    async def _v(email: str) -> str:
        return await verify_email(mv, email)
    return _v


# --- the staged worker ------------------------------------------------------
async def run_generate_job(
    db: AsyncSession,
    job_id: int,
    *,
    anchor: AnchorFn | None = None,
    engines: list | None = None,
    aliaser: AliasFn | None = None,
    widener: WidenFn | None = None,
    matcher: Matcher | None = None,
    bulk_matcher: BulkMatcher | None = None,
    verifier: Verifier | None = None,
    now: datetime | None = None,
) -> None:
    """Six-stage Generate-Leads worker (customer-by-customer, resumable).

    1 Resolve domain (anchor) · 2 Discover (all engines) · 3 Membership check
    (+ user-gated widen) · 4 Dedup → Leads · 5 Apollo enrich · 6 Verify emails.
    """
    run = await _get_run(db, job_id)
    if run is None:
        await jobs_service.mark_error(db, job_id, "Generate-Leads run record missing.")
        return

    try:
        req = GenerateRequest(**json.loads(run.params_json or "{}"))
    except (ValueError, TypeError):
        await jobs_service.mark_error(db, job_id, "Generate-Leads request is unreadable.")
        return

    apify = resolve_api_key("apify")
    if not apify:
        await jobs_service.mark_error(db, job_id, "Apify API key not set — add it in Settings.")
        return
    anthropic = resolve_api_key("anthropic")
    apollo = resolve_api_key("apollo")
    mv = resolve_api_key("millionverifier")
    counter = CallCounter()

    titles = roles.expand_roles(req.role_groups)
    period = credits.current_period(now)

    anchor_fn = anchor or _default_anchor(apify, apollo, counter)
    engine_fns = engines if engines is not None else _default_engines(apify, apollo, counter)
    alias_fn = aliaser or (_default_aliaser(anthropic) if anthropic else None)
    widen_fn = widener or (_default_widener(anthropic) if anthropic else None)
    match_fn = matcher or (_default_matcher(apollo) if apollo else None)
    bulk_match_fn = bulk_matcher or (_default_bulk_matcher(apollo) if apollo else None)
    verify_fn = verifier or (_default_verifier(mv) if mv else None)
    sniper_cats = apollo_native.categories_for_groups(req.role_groups)

    states: dict[str, str] = json.loads(run.customer_states_json or "{}")
    widen_states: dict[str, str] = json.loads(run.widen_states_json or "{}")
    pending = [int(cid) for cid, st in sorted(states.items(), key=lambda kv: int(kv[0]))
               if st == "pending"]
    total_customers = len(states)

    run_cap = int(req.cap) if req.cap and req.cap > 0 else config.DEFAULT_RUN_CAP
    created_total = int((await jobs_service.get_job(db, job_id)).created_count or 0)
    skipped_total = int((await jobs_service.get_job(db, job_id)).skipped_count or 0)
    credits_total = int((await jobs_service.get_job(db, job_id)).credits_used or 0)
    processed = total_customers - len(pending)

    # Cumulative per-stage tallies surfaced in the progress modal (display-only).
    # `created` mirrors the persisted created_count; the rest are in-memory for
    # this worker invocation and restart at 0 on a resume (KI-27) — created stays
    # accurate because it is read back from the job above.
    found_total = 0
    excluded_total = 0
    widened_total = 0
    enriched_total = 0
    verified_total = 0

    def cc() -> dict:
        return {
            "found": found_total,
            "excluded": excluded_total,
            "widened": widened_total,
            "created": created_total,
            "enriched": enriched_total,
            "verified": verified_total,
        }

    runner.clear_pause(job_id)
    await jobs_service.mark_running(
        db, job_id, total=total_customers,
        message=f"Generating leads across {len(pending)} companies…",
    )

    company_cache: dict[str, Company] = {}

    async def _discover(ctx: dict) -> list[dict]:
        out: list[dict] = []
        for name, eng in engine_fns:
            try:
                recs = await eng(ctx) or []
            except (ApifyError, ApolloNativeError):
                continue
            for r in recs:
                if isinstance(r, dict):
                    r.setdefault("_engine", name)  # provenance → lead.source
                    out.append(r)
        return out

    for cid in pending:
        if runner.is_cancelled(job_id):
            runner.clear_cancel(job_id)
            runner.clear_pause(job_id)
            await _save_states(db, run, states)
            await jobs_service.mark_done(db, job_id, message="Run cancelled by user.")
            return
        if runner.is_paused(job_id):
            await _save_states(db, run, states)
            await jobs_service.mark_paused(
                db, job_id,
                message=f"Paused ({processed}/{total_customers} companies). Resume to continue.",
            )
            return

        customer = await db.get(CustomerItem, cid)
        cname = customer.name if customer else f"customer {cid}"
        ccountry = req.country or (customer.country if customer else None)
        ccategory = customer.category if customer else None
        idx = processed + 1

        # ---- STAGE 1: resolve anchor domain (always) ----------------------
        await jobs_service.update_progress(
            db, job_id, detail=_detail(1, cname, idx, total_customers, cc()),
            message=f"[{idx}/{total_customers}] Resolve domain · {cname}",
        )
        anchor_info = await anchor_fn(cname, ccountry, ccategory)
        anchor_domain = (
            membership.registrable(anchor_info.get("domain"))
            or membership.registrable(customer.domain if customer else None)
        )
        website = anchor_info.get("website") or (customer.website if customer else "") or ""
        li_url = anchor_info.get("linkedin_url") or ""
        # Cache a freshly-resolved domain back ONLY when the row has none and the
        # field is not human-locked (OP#13: additive, never clobber verified data).
        if customer and anchor_info.get("domain") and not (customer.domain or "").strip():
            locked = {f.strip() for f in (customer.locked_fields or "").split(",")}
            if "domain" not in locked:
                customer.domain = anchor_info["domain"]
                await db.commit()

        # Advisory aliases (Claude proposes; the gate decides) — once per customer.
        extra_aliases: list[str] = []
        if alias_fn is not None:
            try:
                extra_aliases = await alias_fn(cname)
            except (ApifyError, RuntimeError):
                extra_aliases = []
        aliases = membership.make_aliases(cname, extra_aliases)

        ctx = {
            "company": cname, "domain": anchor_domain, "website": website,
            "linkedin_url": li_url, "titles": titles, "country": ccountry,
            "sniper_categories": sniper_cats,
        }

        # ---- STAGE 2: discover across all engines -------------------------
        await jobs_service.update_progress(
            db, job_id, detail=_detail(2, cname, idx, total_customers, cc()),
            message=f"[{idx}/{total_customers}] Discover (multi-source) · {cname}",
        )
        people: list[dict] = await _discover(ctx)
        found_total += len(people)

        # ---- STAGE 3a: Claude widen — USER-GATED on thin combined results --
        # If discovery is thin (< threshold) AND we can widen, PAUSE and ask the
        # user. Only on a recorded "approved" do we call Claude to rewrite the
        # saturated query; "skipped" proceeds. The decision persists per company.
        if len(people) < config.WIDEN_THRESHOLD and widen_fn is not None:
            decision = widen_states.get(str(cid))
            if decision is None:
                earlier_input = sourcing.build_linkedin_input(cname, titles, ccountry)
                await _save_states(db, run, states)  # this customer stays "pending"
                await jobs_service.update_progress(
                    db, job_id,
                    detail=_detail_widen(cname, idx, total_customers, earlier_input, cid),
                )
                await jobs_service.mark_paused(
                    db, job_id,
                    message=(f"Search saturated for {cname} — confirm whether to ask "
                             f"Claude to widen the search."),
                )
                return
            if decision == "approved":
                await jobs_service.update_progress(
                    db, job_id, detail=_detail(3, cname, idx, total_customers, cc()),
                    message=f"[{idx}/{total_customers}] Widening search · {cname}",
                )
                earlier_input = sourcing.build_linkedin_input(cname, titles, ccountry)
                extra = await widen_fn(earlier_input)
                if extra:
                    widened = roles_union(titles, extra)
                    widened_total += 1
                    people.extend(await _discover({**ctx, "titles": widened}))
            # decision == "skipped" → fall through with the thin hits as-is.

        # ---- STAGE 3b: membership gate (drop non-employees) ---------------
        await jobs_service.update_progress(
            db, job_id, detail=_detail(3, cname, idx, total_customers, cc()),
            message=f"[{idx}/{total_customers}] Membership check · {cname}",
        )

        # ---- STAGE 4: dedup → Leads (only verified employees) -------------
        await jobs_service.update_progress(
            db, job_id, detail=_detail(4, cname, idx, total_customers, cc()),
            message=f"[{idx}/{total_customers}] Saving leads · {cname}",
        )
        new_leads: list[Lead] = []
        per_customer = 0
        for raw in people:
            if created_total >= run_cap or per_customer >= config.PER_CUSTOMER_CAP:
                break
            person = sourcing.map_person(raw)
            if person is None:
                continue
            # THE KI-26 GATE: keep only people whose employer matches the customer.
            decision, _reason = membership.verdict(
                person, raw, anchor_domain=anchor_domain,
                target_name=cname, aliases=aliases,
            )
            if decision != "verified":
                excluded_total += 1
                continue
            try:
                key = dedup_key(
                    first_name=person["first_name"],
                    last_name=person["last_name"],
                    email=person["email"],
                    linkedin_url=person["linkedin_url"],
                    company_name=person["company_name"] or cname,
                )
            except ValueError:
                continue
            exists = (
                await db.execute(select(Lead.id).where(Lead.dedup_key == key))
            ).first()
            if exists:
                skipped_total += 1
                continue
            company = await _get_or_create_company(
                db, person["company_name"] or cname, company_cache
            )
            lead = Lead(
                first_name=person["first_name"],
                last_name=person["last_name"],
                email=person["email"],
                phone=person.get("phone"),
                linkedin_url=person["linkedin_url"],
                title=person["title"],
                # CR-6: `location` is the originating customer's company COUNTRY
                # (structured), not the scraped person-city. category +
                # customer_type + customer_item_id carry the customer's taxonomy
                # so the master Leads list + the campaign lead-mix can derive from
                # the lead itself. All advisory — never load-bearing.
                location=ccountry or person.get("location"),
                category=ccategory,
                customer_type=(customer.ctype if customer else None),
                customer_item_id=cid,
                company=company,
                campaign_id=None,
                dedup_key=key,
                stage="new",
                # source stays "leadgen" (the Generate-Leads provenance other code
                # keys on). The DISCOVERING engine is kept in scrape_raw `_engine`
                # for a later Source badge — no semantic overload here.
                source="leadgen",
                scrape_raw=json.dumps(raw, sort_keys=True, default=str),
            )
            db.add(lead)
            await db.flush()
            db.add(
                LeadEvent(
                    lead_id=lead.id, kind="created", from_value=None,
                    to_value=f"Generate Leads · {cname}",
                    actor_user_id=None, actor_name="Generate Leads",
                )
            )
            new_leads.append(lead)
            created_total += 1
            per_customer += 1
        await db.commit()
        await jobs_service.update_progress(
            db, job_id, created_count=created_total, skipped_count=skipped_total,
            detail=_detail(4, cname, idx, total_customers, cc()),
        )

        # ---- STAGE 5: Apollo enrich the new leads (bulk_match, 10/call) ----
        if (bulk_match_fn is not None or match_fn is not None) and new_leads:
            await jobs_service.update_progress(
                db, job_id, detail=_detail(5, cname, idx, total_customers, cc()),
                message=f"[{idx}/{total_customers}] Enriching · {cname}",
            )
            if bulk_match_fn is not None:
                # Build one identity hint per lead (apollo_id → linkedin → name+domain
                # → email). Trim to what the monthly credit ceiling can afford.
                pairs = [(lead, _bulk_hint(lead, anchor_domain)) for lead in new_leads]
                pairs = [(lead, h) for lead, h in pairs if h]
                affordable = 0
                for n in range(1, len(pairs) + 1):
                    if await credits.would_exceed(db, "apollo", n, period):
                        break
                    affordable = n
                pairs = pairs[:affordable]
                # Enrich batch-by-batch; commit + report after EACH batch so the
                # progress modal advances live instead of freezing at 0/N.
                for start in range(0, len(pairs), _ENRICH_BATCH):
                    batch = pairs[start:start + _ENRICH_BATCH]
                    try:
                        results = await bulk_match_fn([h for _lead, h in batch])
                    except (ApolloNativeError, ApolloError, RuntimeError):
                        results = []
                    matched = 0
                    for (lead, _h), person in zip(batch, results):
                        if not isinstance(person, dict) or not person:
                            continue
                        if person.get("email"):
                            lead.email = person["email"]
                        if person.get("phone") and not lead.phone:
                            lead.phone = person["phone"]
                        if person.get("title") and not lead.title:
                            lead.title = person["title"]
                        if person.get("linkedin_url") and not lead.linkedin_url:
                            lead.linkedin_url = person["linkedin_url"]
                        _merge_meta(lead, person)
                        lead.enriched_at = func.now()
                        matched += 1
                        enriched_total += 1
                    if matched:
                        credits_total += matched
                        await credits.record_usage(db, "apollo", period, matched)
                    await db.commit()
                    await jobs_service.update_progress(
                        db, job_id, credits_used=credits_total,
                        detail=_detail(5, cname, idx, total_customers, cc()),
                    )
            else:
                for lead in new_leads:
                    if await credits.would_exceed(db, "apollo", 1, period):
                        break
                    try:
                        person = await match_fn(_lead_hint(lead))
                    except (ApolloError, RuntimeError):
                        continue
                    credits_total += 1
                    await credits.record_usage(db, "apollo", period, 1)
                    if person.get("email"):
                        lead.email = person["email"]
                    if person.get("phone") and not lead.phone:
                        lead.phone = person["phone"]
                    if person.get("title") and not lead.title:
                        lead.title = person["title"]
                    _merge_meta(lead, person)
                    lead.enriched_at = func.now()
                    enriched_total += 1
                    await db.commit()
            await jobs_service.update_progress(
                db, job_id, credits_used=credits_total,
                detail=_detail(5, cname, idx, total_customers, cc()),
            )

        # ---- STAGE 5b: post-enrich integrity gate -------------------------
        # The authoritative work email only lands at enrich (stage 5); the
        # membership gate (stage 3) could only see name/LinkedIn. Re-check here:
        #   • email domain ≠ company domain → "SalesPath No" (kept + flagged,
        #     NOT send-eligible) — an ex-/wrong-company contact (Apollo returned
        #     the person's CURRENT employer). Status is terminal; skip verify.
        #   • same email as a lead already kept (this batch OR the DB) →
        #     soft-archive the redundant copy: cross-tier dedup that dedup_key
        #     (LinkedIn-first) misses when one record has a LinkedIn URL and the
        #     duplicate carries only the email.
        if new_leads:
            kept: list[Lead] = []
            seen_emails: set[str] = set()
            for lead in new_leads:
                em = normalize_email(lead.email)
                ldom = membership.registrable(em.rsplit("@", 1)[-1]) if em else ""
                if anchor_domain and ldom and ldom != anchor_domain:
                    lead.email_status = OFF_DOMAIN
                    lead.email_checked_at = func.now()
                    db.add(LeadEvent(
                        lead_id=lead.id, kind="email_status", from_value=None,
                        to_value=f"SalesPath No — {ldom} ≠ {anchor_domain}",
                        actor_user_id=None, actor_name="Generate Leads",
                    ))
                    continue
                dup = bool(em) and (
                    em in seen_emails
                    or (await db.execute(
                        select(Lead.id).where(
                            func.lower(Lead.email) == em,
                            Lead.archived.is_(False),
                            Lead.id != lead.id,
                        )
                    )).first() is not None
                )
                if dup:
                    lead.archived = True
                    db.add(LeadEvent(
                        lead_id=lead.id, kind="archived", from_value=None,
                        to_value="Duplicate email (cross-tier)",
                        actor_user_id=None, actor_name="Generate Leads",
                    ))
                    skipped_total += 1
                    continue
                if em:
                    seen_emails.add(em)
                kept.append(lead)
            new_leads = kept
            await db.commit()
            await jobs_service.update_progress(
                db, job_id, skipped_count=skipped_total,
                detail=_detail(6, cname, idx, total_customers, cc()),
            )

        # ---- STAGE 6: verify emails ---------------------------------------
        if verify_fn is not None and new_leads:
            await jobs_service.update_progress(
                db, job_id, detail=_detail(6, cname, idx, total_customers, cc()),
                message=f"[{idx}/{total_customers}] Verifying emails · {cname}",
            )
            for vi, lead in enumerate(new_leads, start=1):
                if not lead.email:
                    lead.email_status = "no_email"
                    continue
                if await credits.would_exceed(db, "millionverifier", 1, period):
                    lead.email_status = UNKNOWN
                    continue
                try:
                    status = await verify_fn(lead.email)
                except (VerifyError, RuntimeError):
                    status = UNKNOWN
                else:
                    credits_total += 1
                    await credits.record_usage(db, "millionverifier", period, 1)
                    verified_total += 1
                lead.email_status = status
                lead.email_checked_at = func.now()
                # Commit + report every batch so the verify counter ticks live and
                # the DB transaction never stays open across many network calls.
                if vi % _ENRICH_BATCH == 0:
                    await db.commit()
                    await jobs_service.update_progress(
                        db, job_id, credits_used=credits_total,
                        detail=_detail(6, cname, idx, total_customers, cc()),
                    )
            await db.commit()
            await jobs_service.update_progress(
                db, job_id, credits_used=credits_total,
                detail=_detail(6, cname, idx, total_customers, cc()),
            )

        # ---- mark this customer done + advance counters -------------------
        states[str(cid)] = "done"
        processed += 1
        await _save_states(db, run, states)
        await jobs_service.update_progress(
            db, job_id, processed=processed, created_count=created_total,
            skipped_count=skipped_total, credits_used=credits_total,
        )
        if created_total >= run_cap:
            break

    # remaining pending (only when the run cap stopped us early) stay "pending".
    still_pending = any(st == "pending" for st in states.values())
    await _save_states(db, run, states)
    if still_pending and created_total >= run_cap:
        await jobs_service.mark_done(
            db, job_id,
            message=(f"Run cap reached: {created_total} leads created · "
                     f"{excluded_total} excluded — not at company · "
                     f"{skipped_total} duplicates skipped · {credits_total} credits."),
        )
        return
    await jobs_service.mark_done(
        db, job_id,
        message=(f"{created_total} leads created · {excluded_total} excluded — not at "
                 f"company · {skipped_total} duplicates skipped · {credits_total} credits "
                 f"· {counter.calls} Apify calls."),
    )


# --- helpers ----------------------------------------------------------------
def roles_union(base: list[str], extra: list[str]) -> list[str]:
    """Deduped, ordered union of base + extra titles (deterministic, case-insensitive)."""
    seen: set[str] = set()
    out: list[str] = []
    for t in list(base) + list(extra):
        if isinstance(t, str) and t.strip():
            low = t.strip().lower()
            if low not in seen:
                seen.add(low)
                out.append(t.strip())
    return out


async def _get_or_create_company(
    db: AsyncSession, name: str | None, cache: dict[str, Company]
) -> Company | None:
    if not name or not name.strip():
        return None
    key = " ".join(name.strip().lower().split())
    if key in cache:
        return cache[key]
    existing = (
        await db.execute(select(Company).where(func.lower(Company.name) == key))
    ).scalars().first()
    company = existing or Company(name=name.strip())
    if existing is None:
        db.add(company)
        await db.flush()
    cache[key] = company
    return company


def _lead_hint(lead: Lead) -> dict:
    return {
        "first_name": lead.first_name or "",
        "last_name": lead.last_name or "",
        "organization_name": lead.company.name if lead.company else "",
        "domain": lead.company.domain if lead.company else "",
        "linkedin_url": lead.linkedin_url or "",
        "email": lead.email or "",
    }


def _bulk_hint(lead: Lead, anchor_domain: str | None) -> dict:
    """One Apollo bulk_match identity hint for a lead. Strongest signal first:
    the carried apollo_id (free-search row) → linkedin_url → name+employer-domain
    → email. Returns {} when no usable identity (skip — don't waste a detail slot)."""
    try:
        raw = json.loads(lead.scrape_raw) if lead.scrape_raw else {}
    except (ValueError, TypeError):
        raw = {}
    aid = raw.get("apollo_id") if isinstance(raw, dict) else None
    if isinstance(aid, str) and aid.strip():
        return {"id": aid.strip()}
    if lead.linkedin_url:
        return {"linkedin_url": lead.linkedin_url}
    dom = membership.registrable(
        (lead.company.domain if lead.company else "") or anchor_domain or ""
    )
    if lead.first_name and lead.last_name and dom:
        return {"first_name": lead.first_name, "last_name": lead.last_name, "domain": dom}
    if lead.email:
        return {"email": lead.email}
    return {}


def _merge_meta(lead: Lead, person: dict) -> None:
    try:
        meta = json.loads(lead.scrape_raw) if lead.scrape_raw else {}
        if not isinstance(meta, dict):
            meta = {}
    except (ValueError, TypeError):
        meta = {}
    if person.get("headline"):
        meta.setdefault("apollo_headline", person["headline"])
    lead.scrape_raw = json.dumps(meta, sort_keys=True, default=str) if meta else lead.scrape_raw


_now = lambda: datetime.now(timezone.utc)  # noqa: E731
