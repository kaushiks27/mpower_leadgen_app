"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, OkText, PrimaryButton } from "@/components/Shared/ui";

type HotReply = {
  lead_id: number;
  name: string;
  email: string | null;
  company: string | null;
  title: string | null;
  unibox_url: string;
};

type CampaignMonitor = {
  campaign_id: number;
  campaign_name: string;
  state: string;
  can_sync: boolean;
  last_synced_at: string | null;
  leads_total: number;
  emailed: number;
  replied: number;
  bounced: number;
  unsubscribed: number;
  unmatched: number;
  hot_replies: HotReply[];
};

type SyncResult = {
  stage_changes: number;
  newly_bounced: number;
  newly_unsubscribed: number;
  suppressed: number;
  leads_pulled: number;
  leads_matched: number;
  leads_unmatched: number;
  monitor: CampaignMonitor;
};

const STATE_PILL: Record<string, string> = {
  live: "bg-ok-green/15 text-ok-green",
  draft: "bg-ink/10 text-ink/60",
  error: "bg-err-red/15 text-err-red",
  not_pushed: "bg-ink/10 text-ink/50",
};

function fmtWhen(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="text-center">
      <div className={"font-heading text-xl font-semibold tabular-nums " + (tone ?? "text-ink")}>
        {value}
      </div>
      <div className="text-[11px] font-mono uppercase tracking-wide text-ink/45">{label}</div>
    </div>
  );
}

export default function MonitorPanel() {
  const [rows, setRows] = useState<CampaignMonitor[]>([]);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncingId, setSyncingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setErr("");
    try {
      const res = await apiFetch("/api/instantly/monitor", { method: "GET" });
      if (!res.ok) throw new ApiError(res.status, "Could not load the monitor.");
      setRows((await res.json()) as CampaignMonitor[]);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load the monitor.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sync = async (id: number) => {
    setErr("");
    setOk("");
    setSyncingId(id);
    try {
      const res = await apiFetch(`/api/campaigns/${id}/instantly-sync`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new ApiError(res.status, b.detail ?? "Sync failed.");
      }
      const r = (await res.json()) as SyncResult;
      setRows((prev) => prev.map((c) => (c.campaign_id === id ? r.monitor : c)));
      const bits = [
        `${r.leads_matched} matched`,
        r.stage_changes ? `${r.stage_changes} advanced` : "",
        r.newly_bounced ? `${r.newly_bounced} bounced` : "",
        r.newly_unsubscribed ? `${r.newly_unsubscribed} unsubbed` : "",
        r.suppressed ? `${r.suppressed} suppressed` : "",
        r.leads_unmatched ? `${r.leads_unmatched} unmatched` : "",
      ].filter(Boolean);
      setOk(`Synced “${r.monitor.campaign_name}” — ${bits.join(" · ")}.`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Sync failed.");
    } finally {
      setSyncingId(null);
    }
  };

  if (loading) {
    return <p className="text-ink/45 font-body text-sm">Loading…</p>;
  }

  if (rows.length === 0) {
    return (
      <div className="bg-surface border border-dashed border-ink/20 rounded-2xl p-10 text-center">
        <h2 className="font-heading text-lg font-semibold text-ink">No campaigns pushed yet</h2>
        <p className="text-ink/55 font-body mt-2 max-w-md mx-auto">
          Push a campaign to Instantly first. Once it is pushed, it appears here with a
          Sync button to pull replies, bounces, and unsubscribes back into mPower.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-ink/55 font-body">
        Pull live status from Instantly into the pipeline. <span className="font-medium">Sync</span>{" "}
        advances replied leads, flags + suppresses bounces and unsubscribes, and lists hot replies.
        It never moves a lead backward or overwrites a manual change.
      </p>

      {err && <ErrorText>{err}</ErrorText>}
      {ok && <OkText>{ok}</OkText>}

      {rows.map((c) => (
        <div key={c.campaign_id} className="bg-surface border border-ink/10 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-heading text-base font-semibold text-ink">{c.campaign_name}</h3>
                <span className={"text-[11px] font-mono px-2 py-0.5 rounded-full capitalize " + (STATE_PILL[c.state] ?? STATE_PILL.not_pushed)}>
                  {c.state}
                </span>
              </div>
              <p className="text-xs text-ink/45 font-body mt-1">Last synced: {fmtWhen(c.last_synced_at)}</p>
            </div>
            <PrimaryButton
              type="button"
              onClick={() => sync(c.campaign_id)}
              disabled={!c.can_sync || syncingId === c.campaign_id}
              className="w-auto px-5"
            >
              {syncingId === c.campaign_id ? "Syncing…" : "Sync"}
            </PrimaryButton>
          </div>

          <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 py-2 border-y border-ink/8">
            <Stat label="Leads" value={c.leads_total} />
            <Stat label="Emailed" value={c.emailed} />
            <Stat label="Replied" value={c.replied} tone="text-mpower-orange" />
            <Stat label="Bounced" value={c.bounced} tone={c.bounced ? "text-err-red" : "text-ink"} />
            <Stat label="Unsub" value={c.unsubscribed} tone={c.unsubscribed ? "text-err-red" : "text-ink"} />
            <Stat label="Unmatched" value={c.unmatched} tone="text-ink/50" />
          </div>

          {c.hot_replies.length > 0 && (
            <div>
              <h4 className="text-xs font-mono uppercase tracking-wide text-ink/45 mb-2">
                Hot replies ({c.hot_replies.length})
              </h4>
              <ul className="divide-y divide-ink/8">
                {c.hot_replies.map((h) => (
                  <li key={h.lead_id} className="flex items-center justify-between py-2">
                    <div className="min-w-0">
                      <p className="text-sm font-body text-ink truncate">
                        {h.name}
                        {h.company ? <span className="text-ink/45"> · {h.company}</span> : null}
                      </p>
                      <p className="text-xs text-ink/45 truncate">{h.email ?? "—"}</p>
                    </div>
                    <a
                      href={h.unibox_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="shrink-0 ml-3 text-xs font-body font-medium text-mpower-orange hover:underline btn-press"
                    >
                      Open in Unibox ↗
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
