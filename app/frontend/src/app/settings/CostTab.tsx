"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText } from "@/components/Shared/ui";

type CostLine = {
  key: string;
  label: string;
  detail: string;
  usd: string; // server-computed decimal strings — rendered as-is, no JS money math
  inr: string;
};

type CostEstimate = {
  emails: number;
  rate: string;
  sending_days: number;
  mailboxes: number;
  per_mailbox_per_day: number;
  lines: CostLine[];
  total_usd: string;
  total_inr: string;
  per_email_inr: string;
  per_lead_inr: string;
};

// Read-only cost-transparency estimator (admin-only). Two live knobs — USD->INR
// rate and monthly email volume — are sent to the backend, which does ALL money
// math in exact Decimal and returns formatted strings. Nothing is saved.
export default function CostTab() {
  const [emails, setEmails] = useState(6000);
  const [rate, setRate] = useState("86");
  const [data, setData] = useState<CostEstimate | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setErr("");
    const r = (rate ?? "").trim();
    if (!r || Number(r) <= 0 || !Number.isFinite(emails) || emails < 1) {
      setErr("Enter a positive email count and a conversion rate above 0.");
      return;
    }
    try {
      const res = await apiFetch(
        `/api/cost/estimate?emails=${emails}&rate=${encodeURIComponent(r)}`,
        { method: "GET" },
      );
      if (!res.ok) throw new ApiError(res.status, "Could not load the estimate.");
      setData((await res.json()) as CostEstimate);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load the estimate.");
    }
  }, [emails, rate]);

  useEffect(() => {
    void load();
  }, [load]);

  const inr = (s: string) =>
    "₹" + Number(s).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="space-y-6 max-w-3xl">
      <p className="text-sm text-ink/55 font-body">
        Read-only monthly cost estimate. Vendor prices are benchmarked at{" "}
        <span className="font-medium">6,000 emails/month</span>; flat items scale linearly with
        your email count. Each mailbox sends max{" "}
        <span className="font-medium">{data?.per_mailbox_per_day ?? 30}/day</span> over a 30-day
        month, so the mailbox count steps up in whole mailboxes. Nothing here is saved.
      </p>

      {/* Knobs */}
      <div className="flex flex-wrap items-end gap-4 bg-surface border border-ink/10 rounded-2xl p-5 shadow-sm">
        <div>
          <label className="block text-xs font-body text-ink/55 mb-1">Emails per month</label>
          <input
            type="number"
            min={1}
            value={emails}
            onChange={(e) => setEmails(Math.max(1, Math.floor(Number(e.target.value) || 0)))}
            className="w-40 px-4 py-2.5 rounded-xl border border-ink/15 font-body text-ink focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 focus:border-mpower-orange btn-press bg-surface"
          />
        </div>
        <div>
          <label className="block text-xs font-body text-ink/55 mb-1">
            Conversion rate (₹ per $1)
          </label>
          <input
            type="number"
            min={0}
            step="0.01"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            className="w-40 px-4 py-2.5 rounded-xl border border-ink/15 font-body text-ink focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 focus:border-mpower-orange btn-press bg-surface"
          />
        </div>
        {data && (
          <div className="text-xs font-mono text-ink/50 pb-2">
            {data.mailboxes} mailbox{data.mailboxes !== 1 ? "es" : ""} needed
          </div>
        )}
      </div>

      {err && <ErrorText>{err}</ErrorText>}

      {data && (
        <div className="bg-surface border border-ink/10 rounded-2xl shadow-sm overflow-hidden">
          <table className="w-full text-sm font-body">
            <thead>
              <tr className="text-left text-ink/45 text-xs border-b border-ink/10">
                <th className="px-5 py-3 font-medium">Cost item</th>
                <th className="px-5 py-3 font-medium">Basis</th>
                <th className="px-5 py-3 font-medium text-right">USD / mo</th>
                <th className="px-5 py-3 font-medium text-right">INR / mo</th>
              </tr>
            </thead>
            <tbody>
              {data.lines.map((l) => (
                <tr key={l.key} className="border-b border-ink/5">
                  <td className="px-5 py-3 text-ink font-medium">{l.label}</td>
                  <td className="px-5 py-3 text-ink/50 text-xs">{l.detail}</td>
                  <td className="px-5 py-3 text-right text-ink/70 tabular-nums">${l.usd}</td>
                  <td className="px-5 py-3 text-right text-ink tabular-nums">{inr(l.inr)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-ink/15 bg-ink/[0.02]">
                <td className="px-5 py-3 font-heading font-semibold text-ink" colSpan={2}>
                  Total / month
                </td>
                <td className="px-5 py-3 text-right font-semibold text-ink/80 tabular-nums">
                  ${data.total_usd}
                </td>
                <td className="px-5 py-3 text-right font-heading font-semibold text-mpower-orange tabular-nums">
                  {inr(data.total_inr)}
                </td>
              </tr>
              <tr className="bg-ink/[0.02]">
                <td className="px-5 py-2.5 text-ink/55 text-xs" colSpan={3}>
                  Cost per lead (≈ per email)
                </td>
                <td className="px-5 py-2.5 text-right text-ink/70 text-xs tabular-nums">
                  {inr(data.per_lead_inr)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
