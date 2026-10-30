"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, PrimaryButton } from "@/components/Shared/ui";
import JobProgressPopup, { type Job } from "@/components/Shared/JobProgressPopup";

// Mirrors backend PushStatus. state: not_pushed | draft | live | error.
type PushStatus = {
  state: string;
  instantly_campaign_id: string | null;
  error: string | null;
  leads_pushed: number;
  leads_failed: number;
  campaign_total: number;
  eligible: number;
  pending: number;
  excluded: number;
  can_push: boolean;
  can_start: boolean;
  reason: string | null;
};

const PILL: Record<string, { label: string; cls: string }> = {
  not_pushed: { label: "Not pushed", cls: "bg-ink/10 text-ink/60" },
  draft: { label: "Draft in Instantly", cls: "bg-amber-100 text-amber-700" },
  live: { label: "Live", cls: "bg-green-100 text-green-700" },
  error: { label: "Error", cls: "bg-red-100 text-red-700" },
};

// Push side of S-8. "Create Instantly Campaign" builds a draft in Instantly with
// the app's exact name/schedule/sequence + eligible leads (gated until every lead
// is verified-valid + icebroken). "Start Campaign" activates it (confirm-gated).
export default function InstantlyPush({
  campaignId,
  reloadKey = 0,
  onJobComplete,
}: {
  campaignId: number;
  reloadKey?: number;
  onJobComplete?: () => void;
}) {
  const [st, setSt] = useState<PushStatus | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [err, setErr] = useState("");

  const loadStatus = useCallback(async () => {
    try {
      const r = await apiFetch(`/api/campaigns/${campaignId}/instantly-status`);
      if (r.ok) setSt((await r.json()) as PushStatus);
    } catch {
      /* best-effort; buttons stay disabled-safe */
    }
  }, [campaignId]);

  const loadLatestJob = useCallback(async () => {
    try {
      const r = await apiFetch(
        `/api/jobs?campaign_id=${campaignId}&kind=instantly_push`,
      );
      if (!r.ok) return;
      const j = (await r.json()) as Job | null;
      if (j) {
        setJobId(j.id);
        if (j.status === "pending" || j.status === "running") setOpen(true);
      }
    } catch {
      /* ignore */
    }
  }, [campaignId]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus, reloadKey]);
  useEffect(() => {
    void loadLatestJob();
  }, [loadLatestJob]);

  const push = async () => {
    if (busy) return;
    setErr("");
    setBusy(true);
    try {
      const res = await apiFetch(`/api/campaigns/${campaignId}/instantly-push`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new ApiError(res.status, payload.detail ?? "Could not push.");
      }
      setJobId((payload as Job).id);
      setOpen(true);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not push.");
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (busy) return;
    setErr("");
    setBusy(true);
    setConfirming(false);
    try {
      const res = await apiFetch(
        `/api/campaigns/${campaignId}/instantly-start`,
        { method: "POST", body: JSON.stringify({}) },
      );
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new ApiError(res.status, payload.detail ?? "Could not start.");
      }
      setSt((cur) => (cur ? { ...cur, ...(payload as PushStatus) } : cur));
      await loadStatus();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not start.");
    } finally {
      setBusy(false);
    }
  };

  const handleDone = () => {
    void loadStatus();
    onJobComplete?.();
  };

  // Pill reflects the EFFECTIVE state: a draft is only "Draft in Instantly" when
  // it is actually startable; a failed/empty draft reads "Not pushed" (retryable).
  const pillKey = st
    ? st.can_start
      ? "draft"
      : st.state === "live"
        ? "live"
        : st.state === "error"
          ? "error"
          : "not_pushed"
    : "not_pushed";
  const pill = PILL[pillKey] ?? PILL.not_pushed;

  const reasonText =
    st?.reason === "missing_key"
      ? "Add an Instantly API key in Settings before pushing."
      : st?.reason === "needs_leads"
        ? "No eligible leads yet — add verified leads from your master list (and write icebreakers there if this campaign requires them)."
        : st?.reason === "not_ready"
          ? `Not all leads are ready — ${st.pending} still need verifying or an icebreaker. Prepare them on the master Leads page, then add them here.`
          : null;

  return (
    <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm space-y-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-heading text-base font-semibold text-ink">
          Send via Instantly
        </h2>
        <span
          className={`text-xs font-body font-medium px-3 py-1 rounded-full ${pill.cls}`}
        >
          {pill.label}
        </span>
      </div>

      {st && (
        <p className="text-xs text-ink/45 font-body">
          {st.eligible} ready to push
          {st.excluded > 0 && ` · ${st.excluded} skipped (not sendable)`}
          {st.pending > 0 && ` · ${st.pending} not ready`}
          {(st.state === "draft" || st.state === "live") &&
            ` · ${st.leads_pushed} pushed`}
          {st.leads_failed > 0 && ` · ${st.leads_failed} failed`}
        </p>
      )}

      <div className="flex flex-wrap gap-3">
        {/* Show Create whenever the campaign is NOT a startable draft and not
            live — i.e. not pushed, errored, or a failed/empty draft (retryable).
            A failed push returns here so the user can fix the cause + retry. */}
        {st && !st.can_start && st.state !== "live" ? (
          <PrimaryButton
            type="button"
            onClick={push}
            disabled={busy || !st?.can_push}
            className="w-auto px-5 disabled:bg-ink/15 disabled:text-ink/40 disabled:cursor-not-allowed"
          >
            {busy ? "Starting…" : "Create Instantly Campaign"}
          </PrimaryButton>
        ) : null}

        {st?.can_start && (
          <PrimaryButton
            type="button"
            onClick={() => setConfirming(true)}
            disabled={busy}
            className="w-auto px-5"
          >
            Start Campaign
          </PrimaryButton>
        )}

        {jobId && !open && (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="text-xs font-body text-mpower-orange hover:underline btn-press"
          >
            View push progress
          </button>
        )}
      </div>

      {reasonText && (
        <p className="text-sm font-body text-ink/55">{reasonText}</p>
      )}

      {st?.state === "error" && st.error && (
        <p className="text-sm font-body text-red-600">Instantly: {st.error}</p>
      )}

      {st?.can_start && (
        <p className="text-xs text-ink/40 font-body">
          Draft created in Instantly. Attach your sending mailboxes there, then
          press Start to begin live sending.
        </p>
      )}

      <p className="text-xs text-ink/40 font-body">
        One campaign here = one campaign in Instantly. Settings, sequence, and
        copy are sent exactly as set in this app. Mailboxes are managed in
        Instantly.
      </p>

      {err && <ErrorText>{err}</ErrorText>}

      {/* Confirm dialog before live sending. */}
      {confirming && st && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
          <div className="bg-surface rounded-2xl shadow-xl border border-ink/10 max-w-md w-full p-6 space-y-4">
            <h3 className="font-heading text-lg font-semibold text-ink">
              Start sending?
            </h3>
            <p className="text-sm font-body text-ink/70">
              This activates the Instantly campaign and begins live emails to{" "}
              <span className="font-semibold">{st.leads_pushed}</span> lead
              {st.leads_pushed === 1 ? "" : "s"}. It cannot be undone from here.
            </p>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="px-4 py-2 rounded-xl text-sm font-body text-ink/60 hover:bg-ink/5 btn-press"
              >
                Cancel
              </button>
              <PrimaryButton
                type="button"
                onClick={start}
                className="w-auto px-5"
              >
                Start sending
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}

      {open && jobId && (
        <JobProgressPopup
          jobId={jobId}
          onClose={() => setOpen(false)}
          onDone={handleDone}
        />
      )}
    </section>
  );
}
