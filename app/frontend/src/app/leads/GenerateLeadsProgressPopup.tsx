"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";
import { type LeadgenJob } from "./leadgenShared";

// 6-stage Generate-Leads progress modal — cloned from CompetitorsSyncPopup.
// Polls GET /api/jobs/{id} every 2s; reads `detail` JSON
// {stage:1..6, current:"<company>", customer_index, customer_total}.

type StageState = "waiting" | "running" | "done" | "failed";

const STAGE_META: { n: number; title: string; sub: string }[] = [
  { n: 1, title: "Resolve domain", sub: "Find each customer's website + LinkedIn page" },
  { n: 2, title: "Discover (multi-source)", sub: "Search Apollo + LinkedIn + the company website" },
  { n: 3, title: "Membership check", sub: "Drop anyone not actually employed at the company" },
  { n: 4, title: "Dedup → Leads", sub: "De-duplicate and write fresh leads to the pipeline" },
  { n: 5, title: "Apollo enrich", sub: "Enrich each lead with email + phone" },
  { n: 6, title: "Verify emails", sub: "Verify deliverability so sends don't bounce" },
];

type StageCounts = {
  found?: number;
  excluded?: number;
  widened?: number;
  created?: number;
  enriched?: number;
  verified?: number;
};

type Detail = {
  stage?: number;
  current?: string;
  customer_index?: number;
  customer_total?: number;
  awaiting_widen?: boolean;
  awaiting_cid?: number;
  earlier_query?: string;
  stage_counts?: StageCounts;
};

// Cumulative per-stage count shown on each stage row (job-wide totals). Stages
// 5/6 carry a ratio (m of leads created) so the row can render a real bar.
function stageCount(
  n: number,
  sc?: StageCounts,
): { text: string; ratio?: [number, number] } | null {
  if (!sc) return null;
  const created = sc.created ?? 0;
  switch (n) {
    case 1:
      return null; // domain resolution has no meaningful per-stage tally
    case 2:
      return sc.found != null ? { text: `${sc.found} found` } : null;
    case 3:
      return sc.excluded != null ? { text: `${sc.excluded} excluded` } : null;
    case 4:
      return { text: `${created} created` };
    case 5:
      return { text: `${sc.enriched ?? 0}/${created} enriched`, ratio: [sc.enriched ?? 0, created] };
    case 6:
      return { text: `${sc.verified ?? 0}/${created} verified`, ratio: [sc.verified ?? 0, created] };
    default:
      return null;
  }
}

function detailOf(job: LeadgenJob | null): { stage: number; d: Detail } {
  if (!job || job.status === "pending") return { stage: 0, d: {} };
  if (job.detail) {
    try {
      const d = JSON.parse(job.detail) as Detail;
      const s = Math.max(0, Math.min(6, Math.round(d.stage ?? 0)));
      return { stage: s, d };
    } catch {
      /* fall through */
    }
  }
  return { stage: job.status === "done" ? 6 : 1, d: {} };
}

function stageStateFor(n: number, ph: number, status?: string): StageState {
  if (status === "done") return "done";
  if (status === "error") return ph === n ? "failed" : ph > n ? "done" : "waiting";
  if (ph > n) return "done";
  if (ph === n) return "running";
  return "waiting";
}

const PILL: Record<StageState, { label: string; cls: string }> = {
  waiting: { label: "Waiting", cls: "bg-ink/10 text-ink/50" },
  running: { label: "Running", cls: "bg-mpower-orange/15 text-mpower-orange" },
  done: { label: "Done", cls: "bg-ok-green/15 text-ok-green" },
  failed: { label: "Failed", cls: "bg-err-red/15 text-err-red" },
};

function StageRow({
  n,
  title,
  sub,
  state,
  count,
  children,
}: {
  n: number;
  title: string;
  sub: string;
  state: StageState;
  count?: string | null;
  children?: React.ReactNode;
}) {
  const p = PILL[state];
  return (
    <div className="rounded-xl border border-ink/10 bg-canvas/60 p-3.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <span
            className={
              "w-6 h-6 shrink-0 rounded-full flex items-center justify-center text-xs font-semibold " +
              (state === "done"
                ? "bg-ok-green/15 text-ok-green"
                : state === "running"
                  ? "bg-mpower-orange/15 text-mpower-orange"
                  : state === "failed"
                    ? "bg-err-red/15 text-err-red"
                    : "bg-ink/10 text-ink/40")
            }
          >
            {state === "done" ? "✓" : n}
          </span>
          <div className="min-w-0">
            <p className="font-body text-sm font-medium text-ink truncate">{title}</p>
            <p className="text-xs text-ink/45 truncate">{sub}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {count ? (
            <span className="text-xs tabular-nums text-ink/55 font-medium">{count}</span>
          ) : null}
          <span className={"px-2 py-0.5 rounded-full text-xs font-medium " + p.cls}>
            {p.label}
          </span>
        </div>
      </div>
      {children}
    </div>
  );
}

const _STOPPED = new Set(["done", "error", "paused"]);
// Sentinel for a TRANSIENT poll failure — deliberately NOT in _STOPPED so a
// momentary blip keeps the 2s poll loop alive (it self-heals on the next tick)
// instead of conflating with the terminal job status "error" and halting forever.
const _POLL_ERR = "__poll_error";

export default function GenerateLeadsProgressPopup({
  jobId,
  onClose,
  onDone,
  onPause,
  onResume,
  onCancel,
}: {
  jobId: number;
  onClose: () => void;
  onDone?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  onCancel?: () => void;
}) {
  const [job, setJob] = useState<LeadgenJob | null>(null);
  const [err, setErr] = useState("");
  const [pausing, setPausing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [widening, setWidening] = useState(false);
  const [pollKey, setPollKey] = useState(0);
  const firedDone = useRef(false);

  const poll = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/jobs/${jobId}`, { method: "GET" });
      if (!res.ok) throw new Error("unavailable");
      const j = (await res.json()) as LeadgenJob;
      setJob(j);
      setErr(""); // a good poll clears any stale "Could not load progress." banner
      if (_STOPPED.has(j.status) && !firedDone.current) {
        firedDone.current = true;
        onDone?.();
      }
      return j.status;
    } catch {
      setErr("Could not load progress.");
      return _POLL_ERR; // transient → keep polling; do NOT treat as terminal
    }
  }, [jobId, onDone]);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;
    firedDone.current = false; // new job (e.g. Resume) → re-arm the done latch
    setPausing(false);
    void (async () => {
      const status = await poll();
      // Keep polling for any NON-terminal first result — pending, running, OR a
      // transient poll error (_POLL_ERR isn't in _STOPPED). A first-poll blip no
      // longer permanently halts progress; the loop recovers on the next tick.
      if (!cancelled && !_STOPPED.has(status)) {
        timer = setInterval(async () => {
          const s = await poll();
          if (_STOPPED.has(s)) if (timer) clearInterval(timer);
        }, 2000);
      }
    })();
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [poll, pollKey]);

  // The user's answer to the "search saturated — widen?" prompt. Records the
  // choice, then the backend resumes the run, so we re-arm polling.
  const decideWiden = useCallback(
    async (approve: boolean) => {
      setWidening(true);
      try {
        const res = await apiFetch("/api/leadgen/widen", {
          method: "POST",
          body: JSON.stringify({ job_id: jobId, approve }),
        });
        if (!res.ok) {
          const body = (await res.json().catch(() => ({}))) as { detail?: string };
          throw new Error(body.detail || "Could not apply your choice.");
        }
        setErr("");
        firedDone.current = false;
        setPollKey((k) => k + 1); // backend resumed the run → restart polling
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Could not apply your choice.");
      } finally {
        setWidening(false);
      }
    },
    [jobId],
  );

  const { stage: ph, d } = detailOf(job);
  const running = job?.status === "pending" || job?.status === "running";
  const custTotal = d.customer_total ?? 0;
  const custIdx = d.customer_index ?? 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/40">
      <div className="bg-surface rounded-2xl shadow-xl border border-ink/10 w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="font-heading text-base font-semibold text-ink">Generate Leads</h3>
            <p className="text-xs font-body text-ink/50 mt-0.5">
              {job?.status === "paused"
                ? "Paused — Resume when you're ready."
                : running
                  ? "Running — close this and it keeps going."
                  : job?.status === "done"
                    ? "Finished."
                    : job?.status === "error"
                      ? "Stopped with an error."
                      : "Starting…"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-ink/40 hover:text-ink btn-press text-lg leading-none px-2"
          >
            ✕
          </button>
        </div>

        {/* Per-customer progress headline */}
        {(custTotal > 0 || d.current) && (
          <div className="rounded-xl bg-mpower-orange/[0.06] border border-mpower-orange/15 px-3.5 py-2.5">
            <p className="text-xs text-ink/55">
              {custTotal > 0 ? (
                <>
                  Customer <span className="tabular-nums font-medium text-ink/75">{custIdx}/{custTotal}</span>
                </>
              ) : (
                "Working"
              )}
              {d.current ? <> · <span className="text-ink/75">{d.current}</span></> : null}
            </p>
            {job && (
              <p className="text-xs text-ink/45 tabular-nums mt-0.5">
                {job.processed}/{job.total} processed · {job.created_count} created
              </p>
            )}
          </div>
        )}

        {/* Saturation — user-confirmed Claude widen (your design: ask first) */}
        {job?.status === "paused" && d.awaiting_widen && (
          <div className="rounded-xl border border-mpower-orange/30 bg-mpower-orange/[0.06] p-3.5 space-y-2.5">
            <p className="text-sm font-medium text-ink">
              Search saturated{d.current ? ` for ${d.current}` : ""}
            </p>
            <p className="text-xs text-ink/60">
              Discovery stopped returning new people. Ask Claude to rewrite the search query
              to surface ~50% more decision-makers?
            </p>
            {d.earlier_query && (
              <pre className="text-[11px] leading-snug bg-ink/[0.04] border border-ink/10 rounded-lg p-2 overflow-x-auto max-h-32 text-ink/70 whitespace-pre-wrap">
                {d.earlier_query}
              </pre>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                disabled={widening}
                onClick={() => void decideWiden(true)}
                className="flex-1 py-2 rounded-xl bg-mpower-orange text-white text-sm font-medium hover:opacity-90 btn-press disabled:opacity-50"
              >
                {widening ? "Working…" : "Widen with Claude"}
              </button>
              <button
                type="button"
                disabled={widening}
                onClick={() => void decideWiden(false)}
                className="flex-1 py-2 rounded-xl border border-ink/15 text-ink/70 text-sm hover:bg-canvas btn-press disabled:opacity-50"
              >
                Skip (use current)
              </button>
            </div>
          </div>
        )}

        {STAGE_META.map((s) => {
          const state = stageStateFor(s.n, ph, job?.status);
          const active = state === "running" || state === "failed";
          const sc = stageCount(s.n, d.stage_counts);
          // Stages 5/6 have a real m/N ratio → bar reflects it; earlier stages
          // have no denominator, so the active row just names the current company.
          const ratioPct =
            sc?.ratio && sc.ratio[1] > 0
              ? Math.min(100, Math.round((sc.ratio[0] / sc.ratio[1]) * 100))
              : null;
          return (
            <StageRow key={s.n} n={s.n} title={s.title} sub={s.sub} state={state} count={sc?.text}>
              {active && job && (
                <div className="mt-2 space-y-1">
                  {ratioPct !== null && (
                    <div className="h-2 rounded-full bg-ink/10 overflow-hidden">
                      <div
                        className={
                          "h-full transition-all duration-500 " +
                          (state === "failed" ? "bg-err-red" : "bg-mpower-orange")
                        }
                        style={{ width: `${ratioPct}%` }}
                      />
                    </div>
                  )}
                  {d.current ? (
                    <p className="text-xs text-ink/55 truncate">{d.current}</p>
                  ) : null}
                </div>
              )}
            </StageRow>
          );
        })}

        <p className="text-sm font-body text-ink/75 min-h-[1.25rem]">
          {err || job?.message || "Waiting for the first update…"}
        </p>

        <div className="flex items-center gap-2">
          {running && onPause && (
            <button
              type="button"
              disabled={pausing}
              onClick={() => {
                setPausing(true);
                onPause();
              }}
              className="flex-1 py-2.5 rounded-xl border border-mpower-orange/40 font-body text-mpower-orange hover:bg-mpower-orange/5 btn-press disabled:opacity-50"
            >
              {pausing ? "Pausing…" : "Pause"}
            </button>
          )}
          {job?.status === "paused" && onResume && !d.awaiting_widen && (
            <button
              type="button"
              onClick={onResume}
              className="flex-1 py-2.5 rounded-xl bg-mpower-orange text-white font-body font-medium hover:opacity-90 btn-press"
            >
              Resume
            </button>
          )}
          {(running || job?.status === "paused") && onCancel && (
            <button
              type="button"
              disabled={cancelling}
              onClick={() => {
                if (!window.confirm("Kill this run and discard it? You'll start fresh next time.")) return;
                setCancelling(true);
                onCancel();
              }}
              className="flex-1 py-2.5 rounded-xl border border-err-red/40 font-body text-err-red hover:bg-err-red/5 btn-press disabled:opacity-50"
            >
              {cancelling ? "Cancelling…" : "Cancel run"}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="flex-1 py-2.5 rounded-xl border border-ink/15 font-body text-ink/70 hover:bg-canvas btn-press"
          >
            {running ? "Close (keeps running)" : "Close"}
          </button>
        </div>
      </div>
    </div>
  );
}
