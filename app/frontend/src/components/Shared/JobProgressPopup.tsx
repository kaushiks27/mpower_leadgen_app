"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";

// One background job's live snapshot (mirrors backend JobOut).
export type Job = {
  id: number;
  campaign_id: number | null;
  kind: string;
  status: "pending" | "running" | "done" | "error";
  total: number;
  processed: number;
  created_count: number;
  skipped_count: number;
  error_count: number;
  credits_used: number;
  message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
};

const TITLE: Record<string, string> = {
  generate_leads: "Generate leads",
  apollo_enrich: "Apollo enrich + verify",
  icebreaker: "Create icebreaker",
  instantly_push: "Push to Instantly",
  brain_sync: "Sync Products & Services",
};

// Closeable + reopenable progress popup. It polls /api/jobs/{id} every 2s while
// the job is running — because the work runs server-side, closing this popup (or
// the whole tab) never stops the job; reopening simply resumes polling. `onDone`
// fires once when the job reaches done/error so the parent can refresh lists.
export default function JobProgressPopup({
  jobId,
  onClose,
  onDone,
}: {
  jobId: number;
  onClose: () => void;
  onDone?: (job: Job) => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState("");
  const firedDone = useRef(false);

  const poll = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/jobs/${jobId}`, { method: "GET" });
      if (!res.ok) throw new Error("status unavailable");
      const j = (await res.json()) as Job;
      setJob(j);
      if ((j.status === "done" || j.status === "error") && !firedDone.current) {
        firedDone.current = true;
        onDone?.(j);
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
          if (s === "done" || s === "error") {
            if (timer) clearInterval(timer);
          }
        }, 2000);
      }
    })();
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [poll]);

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
              {TITLE[job?.kind ?? ""] ?? "Job progress"}
            </h3>
            <p className="text-xs font-body text-ink/50 mt-0.5">
              {running
                ? "Running — you can close this and it keeps going."
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

        <div className="h-2 rounded-full bg-ink/10 overflow-hidden">
          <div
            className={
              "h-full transition-all duration-500 " +
              (job?.status === "error" ? "bg-err-red" : "bg-mpower-orange")
            }
            style={{ width: `${pct}%` }}
          />
        </div>

        <p className="text-sm font-body text-ink/75 min-h-[1.25rem]">
          {err || job?.message || "Waiting for the first update…"}
        </p>

        {job && (
          <dl className="grid grid-cols-3 gap-2 text-center text-xs font-body">
            <Stat label="Processed" value={`${job.processed}/${job.total}`} />
            <Stat label="New / found" value={job.created_count} />
            <Stat label="Credits" value={job.credits_used} />
          </dl>
        )}

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

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl bg-canvas/70 border border-ink/10 py-2">
      <dt className="text-ink/45 uppercase tracking-wide text-[10px]">{label}</dt>
      <dd className="text-ink font-semibold mt-0.5">{value}</dd>
    </div>
  );
}
