"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";

// Job snapshot (mirrors backend JobOut). FIVE stages of the category-first pipeline,
// read from `detail` JSON {"stage":1..5,"current":"…"}; falls back to a message
// heuristic if detail is absent.
type Job = {
  id: number;
  status: "pending" | "running" | "done" | "error" | "paused" | "cancelled";
  total: number;
  processed: number;
  created_count: number;
  message: string | null;
  detail: string | null;
};

type StageState = "waiting" | "running" | "done" | "failed";
type Phase = 0 | 1 | 2 | 3 | 4 | 5 | 6;
type SourceCounts = Record<string, number>;

// Friendly labels for the per-source discovered counts shown under Stage 1.
const SOURCE_LABEL: Record<string, string> = {
  google: "Google",
  maps: "Google Maps",
  linkedin: "LinkedIn",
  indiamart: "IndiaMART",
  thomasnet: "ThomasNet",
  europages: "Europages",
  wlw: "wlw (DACH)",
};

const STAGE_META: { n: number; title: string; sub: string }[] = [
  { n: 1, title: "Discover", sub: "Google + 6 lanes (Maps, LinkedIn, IndiaMART, ThomasNet, Europages, wlw), worldwide + India" },
  { n: 2, title: "Resolve website", sub: "Follow each company to its correct, canonical URL" },
  { n: 3, title: "Crawl → location", sub: "Crawl each site + read it to fill the HQ country" },
  { n: 4, title: "Identify type", sub: "From the same crawl: OEM, Reseller, or Distributor" },
  { n: 5, title: "Classify", sub: "Claude grades the genuine-customer band (battery makers → No)" },
  { n: 6, title: "Enrich contacts", sub: "Apollo + MillionVerifier fill a verified company phone + email" },
];

function phaseOf(job: Job | null): { stage: Phase; current: string; sources: SourceCounts | null } {
  if (!job || job.status === "pending") return { stage: 0, current: "", sources: null };
  if (job.detail) {
    try {
      const d = JSON.parse(job.detail) as { stage?: number; current?: string; sources?: SourceCounts };
      const s = Math.max(0, Math.min(6, Math.round(d.stage ?? 0)));
      return { stage: s as Phase, current: d.current ?? "", sources: d.sources ?? null };
    } catch {
      /* fall through to heuristic */
    }
  }
  if (job.total === 0) return { stage: 1, current: "", sources: null };
  return {
    stage: /^enrich|resolv|crawl|location/i.test(job.message ?? "") ? 3 : 5,
    current: "",
    sources: null,
  };
}

function stageStateFor(n: number, ph: Phase, status?: string): StageState {
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
  children,
}: {
  n: number;
  title: string;
  sub: string;
  state: StageState;
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
        <span className={"px-2 py-0.5 rounded-full text-xs font-medium shrink-0 " + p.cls}>
          {p.label}
        </span>
      </div>
      {children}
    </div>
  );
}

const _STOPPED = new Set(["done", "error", "paused", "cancelled"]);

export default function CustomersSyncPopup({
  jobId,
  onClose,
  onStart,
  onDone,
  onPause,
  onResume,
  onCancel,
}: {
  jobId: number | null;
  onClose: () => void;
  onStart: (perSource: number) => Promise<void>;
  onDone?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  onCancel?: () => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState("");
  const [pausing, setPausing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [perSource, setPerSource] = useState(50);
  const [starting, setStarting] = useState(false);
  const firedDone = useRef(false);

  const poll = useCallback(async () => {
    if (jobId === null) return "pending";
    try {
      const res = await apiFetch(`/api/jobs/${jobId}`, { method: "GET" });
      if (!res.ok) throw new Error("unavailable");
      const j = (await res.json()) as Job;
      setJob(j);
      if (_STOPPED.has(j.status) && !firedDone.current) {
        firedDone.current = true;
        onDone?.();
      }
      return j.status;
    } catch {
      setErr("Could not load progress.");
      return "error";
    }
  }, [jobId, onDone]);

  useEffect(() => {
    if (jobId === null) return; // config phase — nothing to poll yet
    let timer: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;
    firedDone.current = false; // new job (e.g. Resume) → re-arm the done latch
    setPausing(false);
    setCancelling(false);
    void (async () => {
      const status = await poll();
      if (!cancelled && (status === "pending" || status === "running")) {
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
  }, [poll, jobId]);

  const { stage: ph, current, sources } = phaseOf(job);
  const pct =
    job && job.total > 0
      ? Math.min(100, Math.round((job.processed / job.total) * 100))
      : job?.status === "done"
        ? 100
        : 0;
  const running = job?.status === "pending" || job?.status === "running";

  // ---- Config phase: ask "how many results per source?" before starting ----
  if (jobId === null) {
    const start = async () => {
      if (starting) return;
      setStarting(true);
      setErr("");
      try {
        await onStart(Math.max(1, Math.min(1000, Math.round(perSource) || 50)));
      } catch {
        setErr("Could not start the sync.");
        setStarting(false);
      }
    };
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/40">
        <div className="bg-surface rounded-2xl shadow-xl border border-ink/10 w-full max-w-md p-6 space-y-4">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-heading text-base font-semibold text-ink">Sync Customers</h3>
              <p className="text-xs font-body text-ink/50 mt-0.5">
                Discover new companies from Google + 6 sources, then enrich + classify.
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

          <label className="block">
            <span className="text-sm font-body font-medium text-ink">How many results per source?</span>
            <input
              type="number"
              min={1}
              max={1000}
              value={perSource}
              onChange={(e) => setPerSource(Number(e.target.value))}
              onKeyDown={(e) => {
                if (e.key === "Enter") void start();
              }}
              className="mt-1.5 w-full px-3 py-2 text-sm rounded-xl border border-ink/15 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 tabular-nums"
            />
            <span className="block text-xs text-ink/45 mt-1">
              Pulls up to this many <em>new</em> companies from each source — Google, Maps, LinkedIn,
              IndiaMART, ThomasNet, Europages, wlw. Already-saved companies are skipped, so each run
              brings the next batch.
            </span>
          </label>

          {err && <p className="text-err-red text-xs font-body">{err}</p>}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void start()}
              disabled={starting}
              className="flex-1 py-2.5 rounded-xl bg-mpower-orange text-white font-body font-medium hover:opacity-90 btn-press disabled:opacity-50"
            >
              {starting ? "Starting…" : "Start sync"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2.5 rounded-xl border border-ink/15 font-body text-ink/70 hover:bg-canvas btn-press"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/40">
      <div className="bg-surface rounded-2xl shadow-xl border border-ink/10 w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="font-heading text-base font-semibold text-ink">Sync Customers</h3>
            <p className="text-xs font-body text-ink/50 mt-0.5">
              {job?.status === "paused"
                ? "Paused — Resume picks up where it left off."
                : job?.status === "cancelled"
                  ? "Stopped. The next Sync starts fresh."
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

        {STAGE_META.map((s) => {
          const state = stageStateFor(s.n, ph, job?.status);
          const active = state === "running" || state === "failed";
          return (
            <StageRow key={s.n} n={s.n} title={s.title} sub={s.sub} state={state}>
              {s.n === 1 && (state === "done" || ph > 1) && job && (
                <div className="mt-2 space-y-1">
                  <p className="text-xs text-ink/55">
                    {job.created_count > 0
                      ? `${job.created_count} new customer(s) found`
                      : "Discovery complete"}
                  </p>
                  {sources && Object.keys(sources).length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(sources)
                        .sort((a, b) => b[1] - a[1])
                        .map(([src, n]) => (
                          <span
                            key={src}
                            className="px-2 py-0.5 rounded-full text-[11px] font-body bg-ink/5 text-ink/65 tabular-nums"
                          >
                            {SOURCE_LABEL[src] ?? src}: {n}
                          </span>
                        ))}
                    </div>
                  )}
                </div>
              )}
              {s.n > 1 && active && job && (
                <div className="mt-2 space-y-1">
                  <div className="h-2 rounded-full bg-ink/10 overflow-hidden">
                    <div
                      className={
                        "h-full transition-all duration-500 " +
                        (state === "failed" ? "bg-err-red" : "bg-mpower-orange")
                      }
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <p className="text-xs text-ink/55 tabular-nums">
                    {job.processed}/{job.total}
                    {current ? ` · ${current}` : ""}
                  </p>
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
          {job?.status === "paused" && onResume && (
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
                setCancelling(true);
                onCancel();
              }}
              className="flex-1 py-2.5 rounded-xl border border-err-red/40 font-body text-err-red hover:bg-err-red/5 btn-press disabled:opacity-50"
              title="Stop this run permanently. Work done so far is kept; the next Sync starts fresh."
            >
              {cancelling ? "Stopping…" : "Stop"}
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
