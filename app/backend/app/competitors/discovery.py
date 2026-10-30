"""Adaptive discovery loop — keeps widening search until coverage plateaus.

Deterministic Python owns the dedup, the per-round + per-SOURCE counts, and the STOP
decision (plateau OR max-rounds OR max-candidates — whichever first). Claude only
PROPOSES each round's queries (via `propose_fn`); deterministic seeds are the
fallback. Everything is injected so the loop is pure + unit testable without network
or an LLM.

S-MS1 (option-1): the round's queries fan out to Google (`search_fn`) AND every
multi-source lane (`lane_fn`) — so Claude's expanded phrases hit all lanes every
round. All sources merge into ONE unique-by-domain set; the FIRST source to surface a
domain owns the row + its per-source count (counts always sum to the unique total).
Marketplace lanes (IndiaMART) emit no own-domain → buffered, then domain-resolved once
after the loop (`marketplace_resolve_fn`).

A round adds fewer than `plateau_threshold` NEW domains (across all sources) → we've
found essentially everything the current angles reach → stop.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.competitors import sourcing

SearchFn = Callable[[list[str]], Awaitable[list[dict]]]
ProposeFn = Callable[[list[str], int, list[str]], Awaitable[list[str]]]
RoundCb = Callable[[int, int, int], Awaitable[None]]  # (round, new_this_round, total)
LaneFn = Callable[[list[str]], Awaitable[list[dict]]]  # queries -> normalized candidates
ResolveFn = Callable[[list[dict]], Awaitable[list[dict]]]  # domain-less rows -> resolved


def _merge_one(
    cand: dict, *, seen: set, by_dom: dict, candidates: list, counts: dict,
    per_source_cap: int | None = None,
) -> bool:
    """Merge a single candidate into the running set. Returns True iff it was a NEW
    domain (so the caller can count it toward the plateau). A repeat domain only fills
    a blank phone/email (own-domain sources are merged before marketplace). A source at
    its `per_source_cap` ("how many results per source") drops further NEW domains —
    but a same company can still arrive via a not-yet-capped source."""
    dom = (cand.get("domain") or "").strip().lower()
    if not dom:
        return False
    src = cand.get("discovery_source") or "google"
    if dom in seen:
        # A domain already in the DB (pre-seeded into `seen`) has no by_dom row — it's
        # being skipped on a repeat Sync, so there is nothing to fill.
        w = by_dom.get(dom)
        if w is not None:
            if not w.get("phone") and cand.get("phone"):
                w["phone"] = cand["phone"]
            if not w.get("email") and cand.get("email"):
                w["email"] = cand["email"]
        return False
    if per_source_cap is not None and counts.get(src, 0) >= per_source_cap:
        return False  # this source has hit the user's per-source limit
    seen.add(dom)
    row = dict(cand)
    row.setdefault("discovery_source", src)
    by_dom[dom] = row
    candidates.append(row)
    counts[src] = counts.get(src, 0) + 1
    return True


async def run_discovery(
    *,
    search_fn: SearchFn,
    propose_fn: ProposeFn | None,
    categories: list[str],
    max_rounds: int,
    plateau_threshold: int,
    max_queries_per_round: int,
    max_candidates: int | None = None,
    on_round: RoundCb | None = None,
    lane_fn: LaneFn | None = None,
    marketplace_resolve_fn: ResolveFn | None = None,
    per_source_cap: int | None = None,
    seen_domains: set[str] | None = None,
) -> dict:
    """Run the loop → {"candidates", "rounds", "queries", "source_counts"}.

    Candidates are unique-by-domain (first source wins, order preserved). `queries` is
    every query issued; `source_counts` is {source: unique-domains-it-first-found} and
    sums to len(candidates). `per_source_cap` ("results per source") bounds the unique
    companies kept from EACH source (Google + every lane) — the user's Sync knob.
    `seen_domains` pre-loads domains ALREADY in the DB so a repeat Sync skips them and
    the per-source cap fills with NEW companies (the next N) — they never re-enter the
    pipeline. Counts reflect only this run's NEW finds.
    """
    seen: set[str] = set(seen_domains or ())
    by_dom: dict[str, dict] = {}
    candidates: list[dict] = []
    counts: dict[str, int] = {}
    marketplace_buf: list[dict] = []
    issued: list[str] = []
    rounds = 0
    # originating-search attribution: { per-lane query -> {category, ctype} }
    meta_by_query = sourcing.category_query_map(categories)

    for round_idx in range(max_rounds):
        rounds = round_idx + 1
        proposed: list[str] = []
        if propose_fn is not None:
            try:
                proposed = await propose_fn(categories, round_idx, sorted(seen)[:40])
            except Exception:  # noqa: BLE001 — propose is best-effort; fall back
                proposed = []
        # Deterministic seeds FIRST (guarantees the OEM + channel + India staples
        # run every round), then Claude's proposals fill the remaining slots.
        seeds = sourcing.seed_queries(categories, round_idx)
        queries = list(dict.fromkeys(q.strip() for q in [*seeds, *proposed] if q.strip()))[
            :max_queries_per_round
        ]
        issued.extend(queries)

        results = await search_fn(queries)
        google = sourcing.extract_candidates(results, meta_by_query)
        for g in google:
            g["discovery_source"] = "google"

        # Lanes get the SAME round queries (Claude's expanded phrases reach them all).
        lane_cands: list[dict] = []
        if lane_fn is not None:
            try:
                lane_cands = await lane_fn(queries)
            except Exception:  # noqa: BLE001 — a lane failure never sinks discovery
                lane_cands = []

        new_count = 0
        capped = False
        # Google first, then lanes (own-domain ordered before marketplace by lane_fn).
        for cand in [*google, *lane_cands]:
            if not (cand.get("domain") or "").strip():
                marketplace_buf.append(cand)  # resolve to a domain after the loop
                continue
            if _merge_one(
                cand, seen=seen, by_dom=by_dom, candidates=candidates, counts=counts,
                per_source_cap=per_source_cap,
            ):
                new_count += 1
                if max_candidates is not None and len(candidates) >= max_candidates:
                    capped = True
                    break

        if on_round is not None:
            await on_round(rounds, new_count, len(candidates))

        if capped:
            break
        if new_count < plateau_threshold:  # coverage plateau → stop
            break

    # Post-loop: resolve marketplace (domain-less) rows to a canonical domain, then
    # merge them in (own-domain sources already won any shared domain above).
    if marketplace_resolve_fn is not None and marketplace_buf:
        if max_candidates is None or len(candidates) < max_candidates:
            try:
                resolved = await marketplace_resolve_fn(marketplace_buf)
            except Exception:  # noqa: BLE001 — best-effort; keep what we have
                resolved = []
            for cand in resolved:
                if max_candidates is not None and len(candidates) >= max_candidates:
                    break
                _merge_one(
                    cand, seen=seen, by_dom=by_dom, candidates=candidates, counts=counts,
                    per_source_cap=per_source_cap,
                )

    return {
        "candidates": candidates,
        "rounds": rounds,
        "queries": issued,
        "source_counts": counts,
    }
