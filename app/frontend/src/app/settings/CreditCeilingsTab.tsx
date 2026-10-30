"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, OkText, PrimaryButton } from "@/components/Shared/ui";

type Ceiling = {
  provider: string;
  monthly_limit: number;
  used: number;
  remaining: number | null;
  pct: number;
  period: string;
};

const LABEL: Record<string, string> = {
  apollo: "Apollo (enrichment)",
  millionverifier: "MillionVerifier (email checks)",
};

// Admin-only monthly credit ceiling per provider. A ceiling of 0 = no limit.
// At 80% of the ceiling a warning email fires; at 100% new enrich runs are
// blocked. Usage shown is this UTC calendar month.
export default function CreditCeilingsTab() {
  const [rows, setRows] = useState<Ceiling[]>([]);
  const [drafts, setDrafts] = useState<Record<string, number>>({});
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [savingP, setSavingP] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr("");
    try {
      const res = await apiFetch("/api/enrichment/ceilings", { method: "GET" });
      if (!res.ok) throw new ApiError(res.status, "Could not load ceilings.");
      const data = (await res.json()) as Ceiling[];
      setRows(data);
      setDrafts(Object.fromEntries(data.map((r) => [r.provider, r.monthly_limit])));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load ceilings.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (provider: string) => {
    setErr("");
    setOk("");
    setSavingP(provider);
    try {
      const res = await apiFetch(`/api/enrichment/ceilings/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ monthly_limit: Number(drafts[provider]) || 0 }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new ApiError(res.status, b.detail ?? "Could not save.");
      }
      setOk(`${LABEL[provider] ?? provider} ceiling saved.`);
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not save.");
    } finally {
      setSavingP(null);
    }
  };

  return (
    <div className="space-y-6 max-w-2xl">
      <p className="text-sm text-ink/55 font-body">
        Set a monthly credit ceiling per provider. <span className="font-medium">0 = no limit.</span>{" "}
        A warning email fires at 80%; new enrich runs are blocked at 100%.
      </p>

      {rows.map((r) => {
        const near = r.monthly_limit > 0 && r.pct >= 80;
        const full = r.monthly_limit > 0 && r.pct >= 100;
        return (
          <div
            key={r.provider}
            className="bg-surface border border-ink/10 rounded-2xl p-5 shadow-sm space-y-3"
          >
            <div className="flex items-center justify-between">
              <h3 className="font-heading text-sm font-semibold text-ink">
                {LABEL[r.provider] ?? r.provider}
              </h3>
              <span
                className={
                  "text-xs font-body px-2 py-0.5 rounded-full " +
                  (full
                    ? "bg-err-red/15 text-err-red"
                    : near
                      ? "bg-mpower-orange/15 text-mpower-orange"
                      : "bg-ink/8 text-ink/60")
                }
              >
                {r.used} used {r.monthly_limit > 0 ? `· ${r.pct}%` : "· no limit"} ({r.period})
              </span>
            </div>

            {r.monthly_limit > 0 && (
              <div className="h-2 rounded-full bg-ink/10 overflow-hidden">
                <div
                  className={
                    "h-full " + (full ? "bg-err-red" : near ? "bg-mpower-orange" : "bg-ok-green")
                  }
                  style={{ width: `${Math.min(100, r.pct)}%` }}
                />
              </div>
            )}

            <div className="flex items-end gap-3">
              <div>
                <label className="block text-xs font-body text-ink/55 mb-1">
                  Monthly credit ceiling
                </label>
                <input
                  type="number"
                  min={0}
                  value={drafts[r.provider] ?? 0}
                  onChange={(e) =>
                    setDrafts((d) => ({
                      ...d,
                      [r.provider]: Math.max(0, Number(e.target.value) || 0),
                    }))
                  }
                  className="w-36 px-4 py-2.5 rounded-xl border border-ink/15 font-body text-ink focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 focus:border-mpower-orange btn-press bg-surface"
                />
              </div>
              <PrimaryButton
                type="button"
                onClick={() => save(r.provider)}
                disabled={savingP === r.provider}
                className="w-auto px-5"
              >
                {savingP === r.provider ? "Saving…" : "Save"}
              </PrimaryButton>
            </div>
          </div>
        );
      })}

      {err && <ErrorText>{err}</ErrorText>}
      {ok && <OkText>{ok}</OkText>}
    </div>
  );
}
