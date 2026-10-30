"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { ErrorText } from "@/components/Shared/ui";
import { ApiError, apiFetch } from "@/lib/api";
import {
  BAND_BADGE,
  type LeadgenCustomer,
  type LeadgenLists,
  type RoleGroup,
} from "@/app/leads/leadgenShared";

// Read-only window onto the live lists the lead generator uses. NO add / edit /
// delete controls anywhere — everything here auto-updates from the source data.
export default function ListsClient() {
  const [lists, setLists] = useState<LeadgenLists | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch("/api/leadgen/lists", { method: "GET" });
        if (!res.ok) throw new ApiError(res.status, "Could not load lists.");
        setLists((await res.json()) as LeadgenLists);
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "Could not load lists.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <p className="text-sm text-ink/50">Loading…</p>;
  if (err) return <ErrorText>{err}</ErrorText>;
  if (!lists) return null;

  return (
    <div className="space-y-6">
      <p className="text-xs font-body text-ink/45 -mt-2">
        Read-only — these update automatically as your Products, Customers, and
        Roles change.
      </p>

      <div className="grid gap-6 md:grid-cols-3">
        <ChipSection title="Categories" items={lists.categories} />
        <ChipSection title="Type" items={lists.types} />
        <ChipSection title="Country" items={lists.countries} />
      </div>

      <CustomersSection rows={lists.customers} />

      <RolesSection roles={lists.roles} />
    </div>
  );
}

function ChipSection({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="bg-surface border border-ink/10 rounded-2xl p-5 shadow-sm">
      <h2 className="font-heading text-base font-semibold text-ink mb-1">
        {title}{" "}
        <span className="text-ink/40 font-body font-normal">({items.length})</span>
      </h2>
      {items.length === 0 ? (
        <p className="text-sm text-ink/45 py-2">Nothing yet.</p>
      ) : (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {items.map((it) => (
            <span
              key={it}
              className="px-2.5 py-1 rounded-full text-xs font-body bg-ink/[0.06] text-ink/70"
            >
              {it}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

// ── Customers (read-only, frozen-header sortable table) ─────────────────────

type SortKey = "name" | "type" | "country" | "category" | "band";
type SortDir = "asc" | "desc";
type Filter = Set<string> | null;

const BAND_RANK: Record<string, number> = { Sure: 0, Likely: 1, Unsure: 2, No: 3 };
const typeValue = (r: LeadgenCustomer) => r.type ?? "—";
const bandValue = (r: LeadgenCustomer) => r.band ?? "not classified";

function CustomersSection({ rows }: { rows: LeadgenCustomer[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [search, setSearch] = useState("");
  const [fName, setFName] = useState<Filter>(null);
  const [fType, setFType] = useState<Filter>(null);
  const [fCountry, setFCountry] = useState<Filter>(null);
  const [fCat, setFCat] = useState<Filter>(null);
  const [fBand, setFBand] = useState<Filter>(null);

  const nameVals = useMemo(
    () =>
      Array.from(new Set(rows.map((r) => r.name)))
        .filter(Boolean)
        .sort((a, b) => (a ?? "").localeCompare(b ?? "")),
    [rows],
  );
  const typeVals = useMemo(() => {
    const present = new Set(rows.map(typeValue));
    return ["OEM", "Reseller", "Distributor", "—"].filter((t) => present.has(t));
  }, [rows]);
  const countryVals = useMemo(
    () =>
      Array.from(new Set(rows.map((r) => r.country)))
        .filter(Boolean)
        .sort((a, b) => (a ?? "").localeCompare(b ?? "")),
    [rows],
  );
  const catVals = useMemo(
    () =>
      Array.from(new Set(rows.map((r) => r.category)))
        .filter(Boolean)
        .sort((a, b) => (a ?? "").localeCompare(b ?? "")),
    [rows],
  );
  const bandVals = useMemo(() => {
    const present = new Set(rows.map(bandValue));
    return ["Sure", "Likely", "Unsure", "No", "not classified"].filter((b) => present.has(b));
  }, [rows]);

  const view = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = rows.filter(
      (r) =>
        (q === "" ||
          (r.name ?? "").toLowerCase().includes(q) ||
          (r.country ?? "").toLowerCase().includes(q) ||
          (r.category ?? "").toLowerCase().includes(q) ||
          (r.type ?? "").toLowerCase().includes(q)) &&
        (fName === null || fName.has(r.name)) &&
        (fType === null || fType.has(typeValue(r))) &&
        (fCountry === null || fCountry.has(r.country)) &&
        (fCat === null || fCat.has(r.category)) &&
        (fBand === null || fBand.has(bandValue(r))),
    );
    const sorted = [...filtered].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "name") cmp = (a.name ?? "").localeCompare(b.name ?? "");
      else if (sortKey === "type") cmp = typeValue(a).localeCompare(typeValue(b));
      else if (sortKey === "country") cmp = (a.country ?? "").localeCompare(b.country ?? "");
      else if (sortKey === "category") cmp = (a.category ?? "").localeCompare(b.category ?? "");
      else cmp = (BAND_RANK[a.band ?? ""] ?? 9) - (BAND_RANK[b.band ?? ""] ?? 9);
      if (cmp === 0) cmp = (a.name ?? "").localeCompare(b.name ?? ""); // stable tiebreak
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [rows, search, fName, fType, fCountry, fCat, fBand, sortKey, sortDir]);

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir("asc");
    }
  };
  const arrow = (k: SortKey) => (sortKey === k ? (sortDir === "asc" ? " ▲" : " ▼") : "");

  return (
    <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm">
      <h2 className="font-heading text-base font-semibold text-ink mb-1">
        Customers{" "}
        <span className="text-ink/40 font-body font-normal">({rows.length})</span>
      </h2>
      <p className="text-xs text-ink/45 mb-3">
        The customer companies the generator can target. Read-only.
      </p>

      <div className="flex flex-wrap items-center gap-2 mb-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search name, type, country, category…"
          className="px-3 py-1.5 text-sm rounded-lg border border-ink/15 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 flex-1 min-w-[220px]"
        />
        <span className="text-xs text-ink/45 tabular-nums">
          {view.length}/{rows.length}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="text-sm text-ink/45 py-4">No customers yet.</p>
      ) : (
        <div className="overflow-auto max-h-[30rem] border border-ink/10 rounded-xl">
          <table className="w-full text-sm min-w-[820px]">
            <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgba(0,0,0,0.06)]">
              <tr className="text-left text-xs font-mono uppercase tracking-wider text-ink/45">
                <Th label={"Name" + arrow("name")} onSort={() => toggleSort("name")}>
                  <HeaderFilter title="Filter name" values={nameVals} filter={fName} onChange={setFName} />
                </Th>
                <Th label={"Type" + arrow("type")} onSort={() => toggleSort("type")}>
                  <HeaderFilter title="Filter type" values={typeVals} filter={fType} onChange={setFType} />
                </Th>
                <Th label={"Country" + arrow("country")} onSort={() => toggleSort("country")}>
                  <HeaderFilter title="Filter country" values={countryVals} filter={fCountry} onChange={setFCountry} />
                </Th>
                <Th label={"Category" + arrow("category")} onSort={() => toggleSort("category")}>
                  <HeaderFilter title="Filter category" values={catVals} filter={fCat} onChange={setFCat} />
                </Th>
                <Th label={"Band" + arrow("band")} onSort={() => toggleSort("band")}>
                  <HeaderFilter
                    title="Filter band"
                    values={bandVals}
                    filter={fBand}
                    onChange={setFBand}
                    renderLabel={(v) => (v === "not classified" ? v : "SalesPath " + v)}
                  />
                </Th>
                <th className="px-3 py-2.5 font-medium">Website</th>
              </tr>
            </thead>
            <tbody>
              {view.map((r) => (
                <tr key={r.id} className="border-t border-ink/5 hover:bg-canvas/60 align-top">
                  <td className="px-3 py-2.5 font-body text-ink">{r.name}</td>
                  <td className="px-3 py-2.5 text-ink/70 whitespace-nowrap">
                    {r.type ? (
                      <span className="px-2 py-0.5 rounded-full text-xs font-body font-medium bg-mpower-orange/10 text-mpower-orange whitespace-nowrap">
                        {r.type}
                      </span>
                    ) : (
                      <span className="text-ink/35 text-xs">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-ink/70 whitespace-nowrap">{r.country || "—"}</td>
                  <td className="px-3 py-2.5 text-ink/70">{r.category || "—"}</td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    <BandPill band={r.band} />
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    {r.website ? (
                      <a
                        href={r.website}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-mpower-orange hover:underline"
                      >
                        link
                      </a>
                    ) : (
                      <span className="text-ink/35">—</span>
                    )}
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

function BandPill({ band }: { band: string | null }) {
  if (!band) return <span className="text-ink/35 text-xs">not classified</span>;
  const b = BAND_BADGE[band] ?? { label: band, cls: "bg-ink/10 text-ink/60" };
  return (
    <span className={"px-2 py-0.5 rounded-full text-xs font-body font-medium whitespace-nowrap " + b.cls}>
      {b.label}
    </span>
  );
}

// ── Roles (read-only, expandable groups) ────────────────────────────────────

function RolesSection({ roles }: { roles: RoleGroup[] }) {
  return (
    <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm">
      <h2 className="font-heading text-base font-semibold text-ink mb-1">
        Roles{" "}
        <span className="text-ink/40 font-body font-normal">({roles.length})</span>
      </h2>
      <p className="text-xs text-ink/45 mb-4">
        Decision-maker roles we target, each with the job-title variants we match
        on. Read-only.
      </p>
      {roles.length === 0 ? (
        <p className="text-sm text-ink/45 py-2">No roles yet.</p>
      ) : (
        <div className="space-y-2">
          {roles.map((g) => (
            <details key={g.group} className="rounded-xl border border-ink/10 bg-ink/[0.02]">
              <summary className="cursor-pointer select-none px-4 py-2.5 text-sm font-body font-medium text-ink/80 hover:text-ink flex items-center justify-between">
                <span>{g.group}</span>
                <span className="text-xs text-ink/40 tabular-nums">{g.titles.length} title(s)</span>
              </summary>
              <div className="px-4 py-3 border-t border-ink/10 flex flex-wrap gap-1.5">
                {g.titles.length === 0 ? (
                  <span className="text-xs text-ink/40">No title variants.</span>
                ) : (
                  g.titles.map((t) => (
                    <span
                      key={t}
                      className="px-2.5 py-1 rounded-full text-xs font-body bg-ink/[0.06] text-ink/70"
                    >
                      {t}
                    </span>
                  ))
                )}
              </div>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}

// ── Shared table chrome (sort header + portaled column filter) ──────────────

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
    <svg viewBox="0 0 20 20" fill="currentColor" className={"w-3 h-3 " + (active ? "" : "opacity-70")} aria-hidden>
      <path
        fillRule="evenodd"
        d="M2.628 1.601C5.028 1.206 7.49 1 10 1s4.973.206 7.372.601a.75.75 0 0 1 .628.74v2.288a2.25 2.25 0 0 1-.659 1.59l-4.682 4.683a2.25 2.25 0 0 0-.659 1.59v3.037c0 .684-.31 1.33-.844 1.757l-1.937 1.55A.75.75 0 0 1 8 18.25v-5.757a2.25 2.25 0 0 0-.659-1.591L2.659 6.22A2.25 2.25 0 0 1 2 4.629V2.34a.75.75 0 0 1 .628-.74Z"
        clipRule="evenodd"
      />
    </svg>
  );
}

// Google-Sheets-style header filter (portaled, never clipped) — identical UX to
// the Competitors + Customers tables.
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
      const width = 224;
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
        className={"leading-none px-1 rounded btn-press " + (active ? "text-mpower-orange" : "text-ink/35 hover:text-ink/70")}
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
                <button type="button" onClick={() => onChange(null)} className="text-xs text-ink/50 hover:text-ink">
                  Select all
                </button>
                <button type="button" onClick={() => onChange(new Set())} className="text-xs text-mpower-orange hover:underline">
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
                    <label key={v} className="flex items-center gap-2 px-1 py-1 text-sm text-ink cursor-pointer hover:bg-canvas/60 rounded">
                      <input type="checkbox" checked={checked(v)} onChange={() => toggle(v)} className="accent-mpower-orange shrink-0" />
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
