"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorText, Field, PrimaryButton } from "@/components/Shared/ui";
import { ApiError, apiFetch } from "@/lib/api";

import CompetitorsDevReference from "./CompetitorsDevReference";
import CompetitorsSyncPopup from "./CompetitorsSyncPopup";
import CompetitorTable from "./CompetitorTable";
import { type Competitor } from "./competitorsShared";

type Summary = {
  total: number;
  local: number;
  global: number;
  manual: number;
  banded: number;
  last_synced: string | null;
};

type Scope = "global" | "local";

export default function CompetitorsClient() {
  const [items, setItems] = useState<Competitor[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  const [popupOpen, setPopupOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [scope, setScope] = useState<Scope>("global");

  const load = useCallback(async () => {
    setErr("");
    try {
      const res = await apiFetch("/api/brain/competitors", { method: "GET" });
      if (!res.ok) throw new ApiError(res.status, "Could not load competitors.");
      setItems((await res.json()) as Competitor[]);
      const sres = await apiFetch("/api/brain/competitors/summary", { method: "GET" });
      if (sres.ok) setSummary((await sres.json()) as Summary);
      const cres = await apiFetch("/api/brain/competitors/categories", { method: "GET" });
      if (cres.ok) setCategories((await cres.json()) as string[]);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load competitors.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    void (async () => {
      try {
        const r = await apiFetch("/api/brain/competitors/active-sync", { method: "GET" });
        if (r.ok) {
          const data = (await r.json()) as { job: { id: number } | null };
          if (data.job) {
            setJobId(data.job.id);
            setPopupOpen(true);
            setSyncing(true);
          }
        }
      } catch {
        /* ignore */
      }
    })();
  }, [load]);

  // Clicking "Sync Competitors": if a run is still in progress / paused / orphaned,
  // REATTACH to it (so the user can Resume or Stop it) instead of silently starting a
  // new one — a fresh per-source cap only applies once the old run is finished/stopped.
  // Otherwise open the config phase (asks "results per source?").
  const openSync = async () => {
    setErr("");
    try {
      const r = await apiFetch("/api/brain/competitors/active-sync", { method: "GET" });
      if (r.ok) {
        const data = (await r.json()) as { job: { id: number; status: string } | null };
        if (data.job && ["pending", "running", "paused"].includes(data.job.status)) {
          setJobId(data.job.id);
          setPopupOpen(true);
          setSyncing(data.job.status !== "paused");
          return;
        }
      }
    } catch {
      /* fall through to fresh config */
    }
    setJobId(null); // config phase — fresh run with the per-source knob
    setPopupOpen(true);
  };

  const cancelSync = async () => {
    try {
      await apiFetch("/api/brain/competitors/sync/cancel", {
        method: "POST",
        body: JSON.stringify({}),
      });
    } catch {
      /* the popup keeps polling; it will reflect the stopped state */
    }
  };

  // Called by the popup's Start (fresh, with the per-source knob) AND Resume (paused
  // job → the backend ignores per_source and continues where it left off).
  const startSync = async (perSource: number) => {
    setErr("");
    setSyncing(true);
    try {
      const res = await apiFetch("/api/brain/competitors/sync", {
        method: "POST",
        body: JSON.stringify({ per_source: perSource }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new ApiError(res.status, b.detail ?? "Could not start sync.");
      }
      const data = (await res.json()) as { id: number };
      setJobId(data.id);
      setPopupOpen(true);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not start sync.");
      setSyncing(false);
      throw e instanceof Error ? e : new Error("sync failed");
    }
  };

  const pauseSync = async () => {
    try {
      await apiFetch("/api/brain/competitors/sync/pause", {
        method: "POST",
        body: JSON.stringify({}),
      });
    } catch {
      /* the popup keeps polling; it will reflect the paused state */
    }
  };

  const rows = items.filter((i) => i.scope === scope);
  const globalCount = summary?.global ?? items.filter((i) => i.scope === "global").length;
  const localCount = summary?.local ?? items.filter((i) => i.scope === "local").length;

  return (
    <div className="space-y-6">
      {/* Header: summary + Sync */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-ink/55">
          {summary ? (
            <>
              <span className="font-medium text-ink">{summary.total}</span> competitors ·{" "}
              {summary.banded} classified · {summary.manual} manual
              {summary.last_synced && (
                <span className="text-ink/40">
                  {" "}· updated {new Date(summary.last_synced).toLocaleString("en-IN")}
                </span>
              )}
            </>
          ) : (
            "Loading…"
          )}
        </div>
        <div className="flex items-center gap-2">
          {jobId !== null && !popupOpen && (
            <button
              type="button"
              onClick={() => setPopupOpen(true)}
              className="text-sm font-body text-mpower-orange hover:underline btn-press px-2"
            >
              View sync progress
            </button>
          )}
          <PrimaryButton onClick={() => void openSync()} disabled={syncing} className="!w-auto px-5">
            {syncing ? "Syncing…" : "Sync Competitors"}
          </PrimaryButton>
        </div>
      </div>

      {err && <ErrorText>{err}</ErrorText>}

      {/* Global / Local sub-tabs */}
      <div className="flex items-center gap-1 border-b border-ink/10">
        <ScopeTab label="Global" count={globalCount} active={scope === "global"} onClick={() => setScope("global")} />
        <ScopeTab label="Local — India" count={localCount} active={scope === "local"} onClick={() => setScope("local")} />
      </div>

      {loading ? (
        <p className="text-sm text-ink/50">Loading…</p>
      ) : (
        <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm">
          <h2 className="font-heading text-base font-semibold text-ink mb-1">
            {scope === "global" ? "Global competitors" : "Local competitors (India)"}{" "}
            <span className="text-ink/40 font-body font-normal">({rows.length})</span>
          </h2>
          <p className="text-xs text-ink/45 mb-4">
            Drone-battery / pack manufacturers. SalesPath band = how confident we are each
            is a true direct competitor (not a drone OEM, cell-only supplier, or reseller).
          </p>

          <CompetitorTable rows={rows} categories={categories} onChanged={load} />

          <ManualAdd defaultCountry={scope === "local" ? "India" : ""} categories={categories} onChanged={load} />
        </section>
      )}

      <CompetitorsDevReference />

      {popupOpen && (
        <CompetitorsSyncPopup
          jobId={jobId}
          onClose={() => setPopupOpen(false)}
          onStart={startSync}
          onDone={() => {
            setSyncing(false);
            void load();
          }}
          onPause={pauseSync}
          onResume={() => void startSync(50)}
          onCancel={cancelSync}
        />
      )}
    </div>
  );
}

function ScopeTab({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "px-4 py-2 -mb-px text-sm font-body font-medium border-b-2 btn-press " +
        (active
          ? "border-mpower-orange text-mpower-orange"
          : "border-transparent text-ink/55 hover:text-ink")
      }
    >
      {label}
      <span className="ml-1.5 text-xs text-ink/40 tabular-nums">{count}</span>
    </button>
  );
}

function ManualAdd({
  defaultCountry,
  categories,
  onChanged,
}: {
  defaultCountry: string;
  categories: string[];
  onChanged: () => void;
}) {
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [country, setCountry] = useState(defaultCountry);
  const [category, setCategory] = useState("");
  const [sellingTo, setSellingTo] = useState("");
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState("");

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (adding || !name.trim()) return;
    setErr("");
    setAdding(true);
    try {
      const res = await apiFetch("/api/brain/competitors", {
        method: "POST",
        body: JSON.stringify({
          name,
          website: website.trim() || null,
          country: country.trim() || null,
          category: category.trim() || null,
          selling_to: sellingTo.trim() || null,
        }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new ApiError(res.status, b.detail ?? "Could not add competitor.");
      }
      setName("");
      setWebsite("");
      setCountry(defaultCountry);
      setCategory("");
      setSellingTo("");
      onChanged();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Could not add competitor.");
    } finally {
      setAdding(false);
    }
  };

  return (
    <form onSubmit={add} className="flex flex-wrap items-start gap-2 pt-4 mt-4 border-t border-ink/10">
      <div className="flex-1 min-w-[150px]">
        <Field type="text" placeholder="Competitor name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="w-40">
        <Field type="text" placeholder="Website (optional)" value={website} onChange={(e) => setWebsite(e.target.value)} />
      </div>
      <div className="w-28">
        <Field type="text" placeholder="Country" value={country} onChange={(e) => setCountry(e.target.value)} />
      </div>
      <select
        value={category}
        onChange={(e) => setCategory(e.target.value)}
        className="px-3 py-2 text-sm rounded-xl border border-ink/15 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 text-ink/70 w-40"
      >
        <option value="">Category (optional)</option>
        {categories.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
      <div className="w-44">
        <Field type="text" placeholder="Selling to (optional)" value={sellingTo} onChange={(e) => setSellingTo(e.target.value)} />
      </div>
      <PrimaryButton type="submit" disabled={adding || !name.trim()} className="!w-auto px-5">
        {adding ? "Adding…" : "Add"}
      </PrimaryButton>
      {err && (
        <p className="w-full text-err-red text-xs font-body" role="alert">
          {err}
        </p>
      )}
    </form>
  );
}
