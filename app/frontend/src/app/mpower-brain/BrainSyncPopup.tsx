"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";

// Job snapshot (mirrors backend JobOut). Stage is DERIVED, robustly:
//  - pending                       -> queued
//  - running & total == 0          -> Stage 1 (Apify sourcing) in progress
//  - running & total  > 0          -> Stage 2 (Claude classifier) in progress
//  - done                          -> both done
//  - error & total == 0 / > 0      -> failure at stage 1 / stage 2
type Job = {
  id: number;
  status: "pending" | "running" | "done" | "error";
  total: number;
  processed: number;
  created_count: number;
  message: string | null;
};

type StageState = "waiting" | "running" | "done" | "failed";

function stages(job: Job | null): { s1: StageState; s2: StageState } {
  if (!job) return { s1: "waiting", s2: "waiting" };
  if (job.status === "pending") return { s1: "waiting", s2: "waiting" };
  if (job.status === "done") return { s1: "done", s2: "done" };
  if (job.status === "error") {
    return job.total === 0
      ? { s1: "failed", s2: "waiting" }
      : { s1: "done", s2: "failed" };
  }
  // running
  return job.total === 0
    ? { s1: "running", s2: "waiting" }
    : { s1: "done", s2: "running" };
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

export default function BrainSyncPopup({
  jobId,
  onClose,
  onDone,
}: {
  jobId: number;
  onClose: () => void;
  onDone?: () => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState("");
  const firedDone = useRef(false);

  const poll = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/jobs/${jobId}`, { method: "GET" });
      if (!res.ok) throw new Error("unavailable");
      const j = (await res.json()) as Job;
      setJob(j);
      if ((j.status === "done" || j.status === "error") && !firedDone.current) {
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
    let timer: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;
    void (async () => {
      const status = await poll();
      if (!cancelled && (status === "pending" || status === "running")) {
        timer = setInterval(async () => {
          const s = await poll();
          if (s === "done" || s === "error") if (timer) clearInterval(timer);
        }, 2000);
      }
    })();
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [poll]);

  const { s1, s2 } = stages(job);
  const pct =
    job && job.total > 0
      ? Math.min(100, Math.round((job.processed / job.total) * 100))
      : job?.status === "done"
        ? 100
        : 0;
  const running = job?.status === "pending" || job?.status === "running";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/40">
      <div className="bg-surface rounded-2xl shadow-xl border border-ink/10 w-full max-w-md p-6 space-y-4">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="font-heading text-base font-semibold text-ink">
              Sync Products &amp; Services
            </h3>
            <p className="text-xs font-body text-ink/50 mt-0.5">
              {running
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

        <StageRow
          n={1}
          title="Apify sourcing"
          sub="Crawl mpowerlithium.com + pull Shopify catalog"
          state={s1}
        >
          {(s1 === "done" || s2 !== "waiting") && job && (
            <p className="text-xs text-ink/55 mt-2">
              {job.created_count > 0
                ? `${job.created_count} new row(s) sourced`
                : "Catalog sourced (no new rows)"}
            </p>
          )}
        </StageRow>

        <StageRow
          n={2}
          title="Claude classifier"
          sub="Verify each row line-by-line → SalesPath band"
          state={s2}
        >
          {s2 !== "waiting" && job && (
            <div className="mt-2 space-y-1">
              <div className="h-2 rounded-full bg-ink/10 overflow-hidden">
                <div
                  className={
                    "h-full transition-all duration-500 " +
                    (s2 === "failed" ? "bg-err-red" : "bg-mpower-orange")
                  }
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className="text-xs text-ink/55 tabular-nums">
                Verified {job.processed}/{job.total}
              </p>
            </div>
          )}
        </StageRow>

        <p className="text-sm font-body text-ink/75 min-h-[1.25rem]">
          {err || job?.message || "Waiting for the first update…"}
        </p>

        <button
          type="button"
          onClick={onClose}
          className="w-full py-2.5 rounded-xl border border-ink/15 font-body text-ink/70 hover:bg-canvas btn-press"
        >
          {running ? "Close (keeps running)" : "Close"}
        </button>
      </div>
    </div>
  );
}
