"use client";

import { useCallback, useEffect, useState } from "react";

import { ErrorText, Field, PrimaryButton } from "@/components/Shared/ui";
import { ApiError, apiFetch } from "@/lib/api";

import BrainSyncPopup from "./BrainSyncPopup";
import CatalogTable from "./CatalogTable";
import DevReference from "./DevReference";
import { type CatalogItem } from "./catalogShared";

type Summary = {
  products: number;
  services: number;
  manual: number;
  banded: number;
  last_synced: string | null;
};

export default function ProductsServicesClient() {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  const [popupOpen, setPopupOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    setErr("");
    try {
      const res = await apiFetch("/api/brain/catalog", { method: "GET" });
      if (!res.ok) throw new ApiError(res.status, "Could not load the catalog.");
      setItems((await res.json()) as CatalogItem[]);
      const sres = await apiFetch("/api/brain/catalog/summary", { method: "GET" });
      if (sres.ok) setSummary((await sres.json()) as Summary);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load the catalog.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // Reattach to an in-flight sync after a reload, so the popup can reopen.
    void (async () => {
      try {
        const r = await apiFetch("/api/brain/catalog/active-sync", { method: "GET" });
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

  const startSync = async () => {
    setErr("");
    setSyncing(true);
    try {
      const res = await apiFetch("/api/brain/catalog/sync", {
        method: "POST",
        body: JSON.stringify({}),
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
    }
  };

  const products = items.filter((i) => i.kind === "product");
  const services = items.filter((i) => i.kind === "service");

  return (
    <div className="space-y-8">
      {/* Header: summary + Sync */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-ink/55">
          {summary ? (
            <>
              <span className="font-medium text-ink">{summary.products}</span> products ·{" "}
              <span className="font-medium text-ink">{summary.services}</span> services ·{" "}
              {summary.banded} verified · {summary.manual} manual
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
          <PrimaryButton onClick={startSync} disabled={syncing} className="!w-auto px-5">
            {syncing ? "Syncing…" : "Sync Products & Services"}
          </PrimaryButton>
        </div>
      </div>

      {err && <ErrorText>{err}</ErrorText>}

      {loading ? (
        <p className="text-sm text-ink/50">Loading…</p>
      ) : (
        <>
          <CatalogSection title="Products" kind="product" rows={products} onChanged={load} />
          <CatalogSection title="Services" kind="service" rows={services} onChanged={load} />
        </>
      )}

      <DevReference />

      {jobId !== null && popupOpen && (
        <BrainSyncPopup
          jobId={jobId}
          onClose={() => setPopupOpen(false)}
          onDone={() => {
            setSyncing(false);
            void load();
          }}
        />
      )}
    </div>
  );
}

function CatalogSection({
  title,
  kind,
  rows,
  onChanged,
}: {
  title: string;
  kind: "product" | "service";
  rows: CatalogItem[];
  onChanged: () => void;
}) {
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState("");

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (adding || !name.trim()) return;
    setErr("");
    setAdding(true);
    try {
      const res = await apiFetch("/api/brain/catalog", {
        method: "POST",
        body: JSON.stringify({ kind, name, price_inr: price.trim() || null }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new ApiError(res.status, b.detail ?? "Could not add item.");
      }
      setName("");
      setPrice("");
      onChanged();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Could not add item.");
    } finally {
      setAdding(false);
    }
  };

  return (
    <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm">
      <h2 className="font-heading text-base font-semibold text-ink mb-4">
        {title} <span className="text-ink/40 font-body font-normal">({rows.length})</span>
      </h2>

      <CatalogTable rows={rows} onChanged={onChanged} />

      {/* Manual add — protected from sync overwrite */}
      <form onSubmit={add} className="flex flex-wrap items-start gap-2 pt-4 mt-4 border-t border-ink/10">
        <div className="flex-1 min-w-[200px]">
          <Field
            type="text"
            placeholder={`Add a ${kind} manually`}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="w-36">
          <Field
            type="text"
            inputMode="decimal"
            placeholder="Price ₹ (optional)"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
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
    </section>
  );
}
