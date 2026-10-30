"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, PrimaryButton } from "@/components/Shared/ui";
import type { SuppressionRow } from "./types";

export default function SuppressionClient() {
  const [rows, setRows] = useState<SuppressionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [kind, setKind] = useState<"email" | "linkedin_url">("email");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setErr("");
    try {
      const res = await apiFetch("/api/suppression", { method: "GET" });
      if (!res.ok) throw new ApiError(res.status, "Could not load list.");
      setRows((await res.json()) as SuppressionRow[]);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load list.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    if (!value.trim()) return;
    setSaving(true);
    setErr("");
    try {
      const res = await apiFetch("/api/suppression", {
        method: "POST",
        body: JSON.stringify({ kind, value: value.trim(), reason: reason.trim() }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new ApiError(res.status, body.detail ?? "Could not add entry.");
      }
      setValue("");
      setReason("");
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not add entry.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: number) => {
    await apiFetch(`/api/suppression/${id}`, { method: "DELETE" });
    await load();
  };

  return (
    <div className="space-y-6">
      <div className="bg-surface border border-ink/10 rounded-2xl p-5 space-y-3">
        <p className="text-sm font-heading font-semibold text-ink">
          Add a do-not-contact entry
        </p>
        <div className="flex flex-wrap gap-3">
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as "email" | "linkedin_url")}
            className="px-3 py-2 rounded-xl border border-ink/15 text-sm font-body text-ink btn-press focus:outline-none focus:ring-2 focus:ring-mpower-orange/30"
          >
            <option value="email">Email</option>
            <option value="linkedin_url">LinkedIn URL</option>
          </select>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={kind === "email" ? "person@company.com" : "linkedin.com/in/…"}
            className="flex-1 min-w-[220px] px-4 py-2 rounded-xl border border-ink/15 text-sm font-body text-ink placeholder:text-ink/30 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 btn-press"
          />
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="reason (optional)"
            className="w-40 px-4 py-2 rounded-xl border border-ink/15 text-sm font-body text-ink placeholder:text-ink/30 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 btn-press"
          />
          <PrimaryButton onClick={add} disabled={saving} className="w-auto px-5 py-2">
            {saving ? "Adding…" : "Add"}
          </PrimaryButton>
        </div>
        {err ? <ErrorText>{err}</ErrorText> : null}
      </div>

      {loading ? (
        <p className="text-sm text-ink/50">Loading…</p>
      ) : rows.length === 0 ? (
        <div className="bg-surface border border-ink/10 rounded-2xl p-10 text-center">
          <p className="text-sm text-ink/45">
            No one suppressed yet. Anyone you add here is kept out of future sends.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li
              key={r.id}
              className="bg-surface border border-ink/10 rounded-xl px-4 py-3 flex items-center justify-between gap-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-body text-ink truncate">{r.value}</p>
                <p className="text-xs text-ink/40">
                  {r.kind === "email" ? "Email" : "LinkedIn"} · {r.reason ?? "—"}
                  {r.created_by_name ? ` · by ${r.created_by_name}` : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => remove(r.id)}
                className="shrink-0 text-xs font-body text-ink/55 hover:text-err-red hover:underline btn-press"
              >
                remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
