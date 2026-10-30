"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, Field, PrimaryButton } from "@/components/Shared/ui";

type Item = {
  id: number;
  kind: string;
  name: string;
  value: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
};

const KINDS: { kind: string; title: string; namePlaceholder: string; valuePlaceholder: string }[] = [
  { kind: "category", title: "mPower product categories", namePlaceholder: "e.g. Industrial drones", valuePlaceholder: "Notes (optional)" },
  { kind: "target_category", title: "Target customer product categories", namePlaceholder: "e.g. Agri equipment", valuePlaceholder: "Notes (optional)" },
  { kind: "geography", title: "Geographies / markets", namePlaceholder: "e.g. India", valuePlaceholder: "Notes (optional)" },
  { kind: "role", title: "Target roles", namePlaceholder: "e.g. Procurement", valuePlaceholder: "Notes (optional)" },
  { kind: "icp_filter", title: "ICP filters", namePlaceholder: "e.g. Drone OEMs", valuePlaceholder: "Filter value / notes" },
];

function KindSection({
  kind,
  title,
  namePlaceholder,
  valuePlaceholder,
  items,
  reload,
}: {
  kind: string;
  title: string;
  namePlaceholder: string;
  valuePlaceholder: string;
  items: Item[];
  reload: () => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState("");
  const [showArchived, setShowArchived] = useState(false);

  const visible = items.filter((i) => showArchived || !i.archived);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (adding || !name.trim()) return;
    setErr("");
    setAdding(true);
    try {
      const res = await apiFetch("/api/config/items", {
        method: "POST",
        body: JSON.stringify({ kind, name, value: value || null }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new ApiError(res.status, b.detail ?? "Could not add item.");
      }
      setName("");
      setValue("");
      await reload();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Could not add item.");
    } finally {
      setAdding(false);
    }
  };

  const patch = async (id: number, body: Record<string, unknown>) => {
    await apiFetch(`/api/config/items/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    await reload();
  };

  return (
    <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-heading text-base font-semibold text-ink">{title}</h2>
        <label className="flex items-center gap-1.5 text-xs text-ink/50 cursor-pointer">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="accent-mpower-orange"
          />
          Show archived
        </label>
      </div>

      {visible.length === 0 ? (
        <p className="text-sm text-ink/45 mb-4">No items yet.</p>
      ) : (
        <ul className="divide-y divide-ink/10 mb-4">
          {visible.map((i) => (
            <li key={i.id} className="py-2.5 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className={"text-sm font-body truncate " + (i.archived ? "text-ink/40 line-through" : "text-ink")}>
                  {i.name}
                </p>
                {i.value && <p className="text-xs text-ink/45 truncate">{i.value}</p>}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {i.archived ? (
                  <button
                    type="button"
                    onClick={() => patch(i.id, { archived: false })}
                    className="text-xs font-body text-mpower-orange hover:underline btn-press"
                  >
                    restore
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => patch(i.id, { archived: true })}
                    className="text-xs font-body text-ink/55 hover:text-err-red hover:underline btn-press"
                  >
                    archive
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={add} className="flex flex-col sm:flex-row gap-2">
        <Field
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={namePlaceholder}
          className="sm:flex-1"
        />
        <Field
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={valuePlaceholder}
          className="sm:flex-1"
        />
        <PrimaryButton type="submit" disabled={adding || !name.trim()} className="sm:w-28">
          {adding ? "Adding…" : "Add"}
        </PrimaryButton>
      </form>
      {err && <div className="mt-2"><ErrorText>{err}</ErrorText></div>}
    </section>
  );
}

export default function CatalogTab() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [listErr, setListErr] = useState("");

  const load = useCallback(async () => {
    setListErr("");
    try {
      const res = await apiFetch("/api/config/items?include_archived=true", {
        method: "GET",
      });
      if (!res.ok) throw new ApiError(res.status, "Could not load catalog.");
      setItems((await res.json()) as Item[]);
    } catch (e) {
      setListErr(e instanceof ApiError ? e.message : "Could not load catalog.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p className="text-sm text-ink/50">Loading…</p>;
  if (listErr) return <ErrorText>{listErr}</ErrorText>;

  return (
    <div className="space-y-6">
      {KINDS.map((k) => (
        <KindSection
          key={k.kind}
          {...k}
          items={items.filter((i) => i.kind === k.kind)}
          reload={load}
        />
      ))}
    </div>
  );
}
