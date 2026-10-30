"use client";

import { useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { apiFetch } from "@/lib/api";

import { BAND_RANK, BandPill, type CatalogItem, formatPrice } from "./catalogShared";

type SortKey = "name" | "category" | "price" | "band";
type SortDir = "asc" | "desc";
type Filter = Set<string> | null; // null = all shown; Set = only those values

const bandValue = (r: CatalogItem) => r.band ?? "not verified";
const catValue = (r: CatalogItem) => r.category ?? "—";
const priceValue = (r: CatalogItem) => r.price_inr ?? "—";

export default function CatalogTable({
  rows,
  onChanged,
}: {
  rows: CatalogItem[];
  onChanged: () => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [search, setSearch] = useState("");
  const [fName, setFName] = useState<Filter>(null);
  const [fCat, setFCat] = useState<Filter>(null);
  const [fPrice, setFPrice] = useState<Filter>(null);
  const [fBand, setFBand] = useState<Filter>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [editVal, setEditVal] = useState("");
  const [busy, setBusy] = useState(false);

  // Distinct values per column (for the checkbox dropdowns).
  const nameVals = useMemo(
    () => Array.from(new Set(rows.map((r) => r.name))).sort((a, b) => a.localeCompare(b)),
    [rows],
  );
  const catVals = useMemo(
    () => Array.from(new Set(rows.map(catValue))).sort((a, b) => a.localeCompare(b)),
    [rows],
  );
  const priceVals = useMemo(
    () =>
      Array.from(new Set(rows.map(priceValue))).sort((a, b) => {
        if (a === "—") return 1;
        if (b === "—") return -1;
        return (Number(a) || 0) - (Number(b) || 0);
      }),
    [rows],
  );
  const bandVals = useMemo(() => {
    const present = new Set(rows.map(bandValue));
    return ["Sure", "Likely", "Unsure", "No", "not verified"].filter((b) => present.has(b));
  }, [rows]);

  const view = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = rows.filter(
      (r) =>
        (q === "" ||
          r.name.toLowerCase().includes(q) ||
          (r.category ?? "").toLowerCase().includes(q) ||
          (r.price_inr ?? "").includes(q)) &&
        (fName === null || fName.has(r.name)) &&
        (fCat === null || fCat.has(catValue(r))) &&
        (fPrice === null || fPrice.has(priceValue(r))) &&
        (fBand === null || fBand.has(bandValue(r))),
    );
    const sorted = [...filtered].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "name") cmp = a.name.localeCompare(b.name);
      else if (sortKey === "category") cmp = catValue(a).localeCompare(catValue(b));
      else if (sortKey === "price")
        cmp = (Number(a.price_inr) || 0) - (Number(b.price_inr) || 0);
      else cmp = (BAND_RANK[a.band ?? ""] ?? 9) - (BAND_RANK[b.band ?? ""] ?? 9);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [rows, search, fName, fCat, fPrice, fBand, sortKey, sortDir]);

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir("asc");
    }
  };
  const arrow = (k: SortKey) => (sortKey === k ? (sortDir === "asc" ? " ▲" : " ▼") : "");

  const savePrice = async (id: number) => {
    setBusy(true);
    try {
      await apiFetch(`/api/brain/catalog/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ price_inr: editVal.trim() || null }),
      });
      setEditId(null);
      onChanged();
    } finally {
      setBusy(false);
    }
  };
  const archive = async (id: number) => {
    await apiFetch(`/api/brain/catalog/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ archived: true }),
    });
    onChanged();
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search name, category, price…"
          className="px-3 py-1.5 text-sm rounded-lg border border-ink/15 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 flex-1 min-w-[200px]"
        />
        <span className="text-xs text-ink/45 tabular-nums">
          {view.length}/{rows.length}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="text-sm text-ink/45 py-4">
          Nothing yet — add one below or hit “Sync Products &amp; Services”.
        </p>
      ) : (
        <div className="overflow-auto max-h-[26rem] border border-ink/10 rounded-xl">
          <table className="w-full text-sm min-w-[680px]">
            <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgba(0,0,0,0.06)]">
              <tr className="text-left text-xs font-mono uppercase tracking-wider text-ink/45">
                <Th label={"Name" + arrow("name")} onSort={() => toggleSort("name")}>
                  <HeaderFilter title="Filter name" values={nameVals} filter={fName} onChange={setFName} />
                </Th>
                <Th label={"Category" + arrow("category")} onSort={() => toggleSort("category")}>
                  <HeaderFilter title="Filter category" values={catVals} filter={fCat} onChange={setFCat} />
                </Th>
                <Th label={"Price" + arrow("price")} onSort={() => toggleSort("price")}>
                  <HeaderFilter
                    title="Filter price"
                    values={priceVals}
                    filter={fPrice}
                    onChange={setFPrice}
                    renderLabel={(v) => (v === "—" ? "—" : formatPrice(v))}
                  />
                </Th>
                <Th label={"SalesPath label" + arrow("band")} onSort={() => toggleSort("band")}>
                  <HeaderFilter
                    title="Filter SalesPath label"
                    values={bandVals}
                    filter={fBand}
                    onChange={setFBand}
                    renderLabel={(v) => (v === "not verified" ? v : "SalesPath " + v)}
                  />
                </Th>
                <th className="px-3 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {view.map((r) => (
                <tr key={r.id} className="border-t border-ink/5 hover:bg-canvas/60">
                  <td className="px-3 py-2.5 font-body text-ink align-top">
                    {r.name}
                    {r.manual && (
                      <span className="ml-2 text-[10px] uppercase tracking-wide text-mpower-orange/80 bg-mpower-orange/10 px-1.5 py-0.5 rounded">
                        manual
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-ink/65 align-top whitespace-nowrap">
                    {r.category ?? "—"}
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap align-top">
                    {editId === r.id ? (
                      <span className="flex items-center gap-1">
                        <input
                          autoFocus
                          value={editVal}
                          inputMode="decimal"
                          onChange={(e) => setEditVal(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void savePrice(r.id);
                            if (e.key === "Escape") setEditId(null);
                          }}
                          className="w-24 px-2 py-1 text-sm rounded border border-mpower-orange/50 focus:outline-none"
                        />
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void savePrice(r.id)}
                          className="text-xs text-ok-green hover:underline btn-press"
                        >
                          save
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditId(null)}
                          className="text-xs text-ink/40 hover:text-ink btn-press"
                        >
                          ✕
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => {
                          setEditId(r.id);
                          setEditVal(r.price_inr ?? "");
                        }}
                        className="group inline-flex items-center gap-1 tabular-nums text-ink/80 hover:text-ink btn-press"
                        title="Click to override price"
                      >
                        {formatPrice(r.price_inr)}
                        {r.price_locked && (
                          <span
                            className="text-[10px] text-mpower-orange/80"
                            title="Manually overridden — survives sync"
                          >
                            • edited
                          </span>
                        )}
                        <span className="opacity-0 group-hover:opacity-100 text-ink/30">✎</span>
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2.5 align-top">
                    <BandPill item={r} />
                  </td>
                  <td className="px-3 py-2.5 text-right align-top">
                    <button
                      type="button"
                      onClick={() => void archive(r.id)}
                      className="text-xs font-body text-ink/40 hover:text-err-red btn-press"
                      title="Archive (soft-remove; reversible)"
                    >
                      archive
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Th({
  label,
  onSort,
  children,
}: {
  label: string;
  onSort: () => void;
  children?: React.ReactNode;
}) {
  return (
    <th className="px-3 py-2.5 font-medium">
      <span className="inline-flex items-center gap-1">
        <button type="button" onClick={onSort} className="cursor-pointer select-none hover:text-ink">
          {label}
        </button>
        {children}
      </span>
    </th>
  );
}

function FunnelIcon({ active }: { active: boolean }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      className={"w-3 h-3 " + (active ? "" : "opacity-70")}
      aria-hidden
    >
      <path
        fillRule="evenodd"
        d="M2.628 1.601C5.028 1.206 7.49 1 10 1s4.973.206 7.372.601a.75.75 0 0 1 .628.74v2.288a2.25 2.25 0 0 1-.659 1.59l-4.682 4.683a2.25 2.25 0 0 0-.659 1.59v3.037c0 .684-.31 1.33-.844 1.757l-1.937 1.55A.75.75 0 0 1 8 18.25v-5.757a2.25 2.25 0 0 0-.659-1.591L2.659 6.22A2.25 2.25 0 0 1 2 4.629V2.34a.75.75 0 0 1 .628-.74Z"
        clipRule="evenodd"
      />
    </svg>
  );
}

// Google-Sheets-style header filter: a funnel button → checkbox popover of the
// column's distinct values, with a search box inside for long lists.
// The popover is portaled to <body> with position:fixed so it is never clipped
// by the table's overflow:auto scroll container (root cause of the hidden-menu bug).
function HeaderFilter({
  title,
  values,
  filter,
  onChange,
  renderLabel = (v) => v,
}: {
  title: string;
  values: string[];
  filter: Filter;
  onChange: (f: Filter) => void;
  renderLabel?: (v: string) => string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const btnRef = useRef<HTMLButtonElement>(null);
  const active = filter !== null;
  const checked = (v: string) => filter === null || filter.has(v);

  const toggleMenu = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      const width = 224; // w-56
      const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
      setPos({ top: r.bottom + 4, left });
    }
    setOpen((o) => !o);
  };

  const toggle = (v: string) => {
    const base = filter === null ? new Set(values) : new Set(filter);
    if (base.has(v)) base.delete(v);
    else base.add(v);
    onChange(base.size === values.length ? null : base);
  };

  const shown = q.trim()
    ? values.filter((v) => renderLabel(v).toLowerCase().includes(q.trim().toLowerCase()))
    : values;

  return (
    <span className="inline-flex">
      <button
        ref={btnRef}
        type="button"
        onClick={toggleMenu}
        title={title}
        className={
          "leading-none px-1 rounded btn-press " +
          (active ? "text-mpower-orange" : "text-ink/35 hover:text-ink/70")
        }
      >
        <FunnelIcon active={active} />
      </button>
      {open &&
        typeof document !== "undefined" &&
        createPortal(
          <>
            <button
              type="button"
              aria-hidden
              tabIndex={-1}
              onClick={() => setOpen(false)}
              className="fixed inset-0 z-40 cursor-default"
            />
            <div
              style={{ position: "fixed", top: pos.top, left: pos.left }}
              className="z-50 w-56 bg-surface border border-ink/15 rounded-lg shadow-xl p-2 font-body"
            >
              <div className="flex justify-between px-1 pb-1.5 mb-1 border-b border-ink/10">
                <button
                  type="button"
                  onClick={() => onChange(null)}
                  className="text-xs text-ink/50 hover:text-ink"
                >
                  Select all
                </button>
                <button
                  type="button"
                  onClick={() => onChange(new Set())}
                  className="text-xs text-mpower-orange hover:underline"
                >
                  Clear
                </button>
              </div>
              {values.length > 8 && (
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search…"
                  className="w-full mb-1 px-2 py-1 text-xs rounded border border-ink/15 focus:outline-none focus:ring-1 focus:ring-mpower-orange/40"
                />
              )}
              <div className="max-h-56 overflow-auto">
                {shown.length === 0 ? (
                  <p className="text-xs text-ink/40 px-1 py-1">No matches</p>
                ) : (
                  shown.map((v) => (
                    <label
                      key={v}
                      className="flex items-center gap-2 px-1 py-1 text-sm text-ink cursor-pointer hover:bg-canvas/60 rounded"
                    >
                      <input
                        type="checkbox"
                        checked={checked(v)}
                        onChange={() => toggle(v)}
                        className="accent-mpower-orange shrink-0"
                      />
                      <span className="truncate">{renderLabel(v)}</span>
                    </label>
                  ))
                )}
              </div>
            </div>
          </>,
          document.body,
        )}
    </span>
  );
}
