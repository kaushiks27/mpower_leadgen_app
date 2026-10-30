"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText } from "@/components/Shared/ui";
import { emailStatusBadge, type Lead } from "../leads/types";

// 08062026_cr CR-2 — the reusable Add-Leads picker body. Fetches master leads
// eligible to pull into a campaign (unassigned + SalesPath Sure/Likely + email +
// icebreaker-if-required) and lets the user tick which to add. Selection is
// LIFTED to the parent so both the create-campaign modal and the detail
// Add-Leads modal share the exact same picker.
export default function LeadPickerList({
  requireIcebreaker,
  selected,
  onToggle,
  onSelectAllShown,
  onClear,
}: {
  requireIcebreaker: boolean;
  selected: Set<number>;
  onToggle: (id: number) => void;
  onSelectAllShown: (ids: number[]) => void;
  onClear: () => void;
}) {
  const [rows, setRows] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const [category, setCategory] = useState("");
  const [ctype, setCtype] = useState("");
  const [country, setCountry] = useState("");
  const [q, setQ] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const params = new URLSearchParams();
      params.set("require_icebreaker", String(requireIcebreaker));
      if (category) params.set("category", category);
      if (ctype) params.set("customer_type", ctype);
      if (country) params.set("country", country);
      if (q.trim()) params.set("q", q.trim());
      const res = await apiFetch(`/api/leads/addable?${params.toString()}`, {
        method: "GET",
      });
      if (!res.ok) throw new ApiError(res.status, "Could not load leads.");
      setRows((await res.json()) as Lead[]);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load leads.");
    } finally {
      setLoading(false);
    }
  }, [requireIcebreaker, category, ctype, country, q]);

  useEffect(() => {
    void load();
  }, [load]);

  // Distinct filter options derived from the loaded eligible set.
  const cats = useMemo(
    () => Array.from(new Set(rows.map((r) => r.category).filter(Boolean) as string[])).sort(),
    [rows],
  );
  const types = useMemo(
    () =>
      Array.from(new Set(rows.map((r) => r.customer_type).filter(Boolean) as string[])).sort(),
    [rows],
  );
  const countries = useMemo(
    () => Array.from(new Set(rows.map((r) => r.location).filter(Boolean) as string[])).sort(),
    [rows],
  );

  const SELECT_CLS =
    "px-2.5 py-1.5 text-sm rounded-lg border border-ink/15 bg-surface focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 text-ink/80";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select className={SELECT_CLS} value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {cats.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select className={SELECT_CLS} value={ctype} onChange={(e) => setCtype(e.target.value)}>
          <option value="">All types</option>
          {types.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <select className={SELECT_CLS} value={country} onChange={(e) => setCountry(e.target.value)}>
          <option value="">All countries</option>
          {countries.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search name, company, email…"
          className="flex-1 min-w-[160px] px-3 py-1.5 text-sm rounded-lg border border-ink/15 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30"
        />
      </div>

      <div className="flex items-center justify-between text-xs">
        <span className="text-ink/45 tabular-nums">
          {selected.size} selected · {rows.length} eligible
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onSelectAllShown(rows.map((r) => r.id))}
            className="text-ink/55 hover:text-ink btn-press"
          >
            Select all shown
          </button>
          <span className="text-ink/20">·</span>
          <button
            type="button"
            onClick={onClear}
            className="text-mpower-orange hover:underline btn-press"
          >
            Clear
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-ink/50 py-4">Loading…</p>
      ) : err ? (
        <ErrorText>{err}</ErrorText>
      ) : rows.length === 0 ? (
        <p className="text-sm text-ink/45 py-4">
          No eligible leads. Leads must be unassigned and verified (SalesPath
          Sure/Likely)
          {requireIcebreaker ? " with an icebreaker" : ""}.
        </p>
      ) : (
        <div className="max-h-72 overflow-auto rounded-xl border border-ink/10 divide-y divide-ink/5">
          {rows.map((l) => {
            const b = emailStatusBadge(l.email_status);
            return (
              <label
                key={l.id}
                className="flex items-center gap-2.5 px-3 py-2 text-sm cursor-pointer hover:bg-canvas/60"
              >
                <input
                  type="checkbox"
                  checked={selected.has(l.id)}
                  onChange={() => onToggle(l.id)}
                  className="accent-mpower-orange shrink-0"
                />
                <span className="font-body text-ink truncate">{l.full_name}</span>
                <span className="text-xs text-ink/45 truncate">{l.company_name ?? "—"}</span>
                {b && (
                  <span className={"text-xs px-1.5 py-0.5 rounded-full shrink-0 " + b.cls}>
                    {b.label}
                  </span>
                )}
                <span className="text-xs text-ink/40 ml-auto shrink-0">{l.location ?? "—"}</span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
