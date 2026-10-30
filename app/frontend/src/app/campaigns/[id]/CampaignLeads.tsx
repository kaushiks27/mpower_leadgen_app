"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText } from "@/components/Shared/ui";
import { IcebreakerCell } from "../../leads/LeadsListClient";
import { STAGE_LABEL, emailStatusBadge, type Lead } from "../../leads/types";

// This campaign's own lead list. Reloads whenever `refreshKey` changes (the
// parent bumps it after a Generate-Leads run).
export default function CampaignLeads({
  campaignId,
  refreshKey,
}: {
  campaignId: number;
  refreshKey: number;
}) {
  const [rows, setRows] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setErr("");
    try {
      const res = await apiFetch(`/api/leads?campaign_id=${campaignId}`, {
        method: "GET",
      });
      if (!res.ok) throw new ApiError(res.status, "Could not load leads.");
      setRows((await res.json()) as Lead[]);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load leads.");
    } finally {
      setLoading(false);
    }
  }, [campaignId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  return (
    <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-base font-semibold text-ink">
          Leads in this campaign
        </h2>
        <span className="text-xs text-ink/40">
          {rows.length} lead{rows.length === 1 ? "" : "s"}
        </span>
      </div>

      {loading ? (
        <p className="text-sm text-ink/50">Loading…</p>
      ) : err ? (
        <ErrorText>{err}</ErrorText>
      ) : rows.length === 0 ? (
        <p className="text-sm text-ink/45">
          No leads yet — click “Add Leads from List” above to pull prepared leads
          into this campaign.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[640px]">
            <thead>
              <tr className="text-left text-xs font-mono uppercase tracking-wider text-ink/40 border-b border-ink/10">
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Company</th>
                <th className="px-3 py-2 font-medium">Title</th>
                <th className="px-3 py-2 font-medium">Email</th>
                <th className="px-3 py-2 font-medium">Verify</th>
                <th className="px-3 py-2 font-medium">Phone</th>
                <th className="px-3 py-2 font-medium">Icebreaker</th>
                <th className="px-3 py-2 font-medium">Stage</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((l) => (
                <tr key={l.id} className="border-b border-ink/5 last:border-0">
                  <td className="px-3 py-2 font-body text-ink font-medium whitespace-nowrap">
                    {l.full_name}
                  </td>
                  <td className="px-3 py-2 text-ink/70 whitespace-nowrap">
                    {l.company_name ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-ink/70 whitespace-nowrap">
                    {l.title ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-ink/70 whitespace-nowrap">
                    {l.email ?? "—"}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {(() => {
                      const b = emailStatusBadge(l.email_status);
                      return b ? (
                        <span
                          className={
                            "px-2 py-0.5 rounded-full text-xs font-body font-medium " +
                            b.cls
                          }
                        >
                          {b.label}
                        </span>
                      ) : (
                        <span className="text-ink/30">—</span>
                      );
                    })()}
                  </td>
                  <td className="px-3 py-2 text-ink/70 whitespace-nowrap">
                    {l.phone ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    <IcebreakerCell lead={l} onChanged={load} />
                  </td>
                  <td className="px-3 py-2">
                    <span className="px-2 py-0.5 rounded-full text-xs font-body font-medium bg-mpower-orange/10 text-mpower-orange">
                      {STAGE_LABEL[l.stage]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
