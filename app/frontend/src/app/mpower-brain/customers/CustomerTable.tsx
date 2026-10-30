"use client";

import { useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { apiFetch } from "@/lib/api";

import { BAND_RANK, BandPill, CtypePill, CTYPES, type Customer } from "./customersShared";

type SortKey = "name" | "country" | "ctype" | "category" | "band";
type SortDir = "asc" | "desc";
type Filter = Set<string> | null; // null = all shown; Set = only those values
type EditField = "name" | "country" | "ctype" | "category" | "website";

const bandValue = (r: Customer) => r.band ?? "not classified";
const countryValue = (r: Customer) => r.country ?? "—";
const catValue = (r: Customer) => r.category ?? "—";
const ctypeValue = (r: Customer) => r.ctype ?? "—";
const isLocked = (r: Customer, f: string) => r.locked_fields.includes(f);

export default function CustomerTable({
  rows,
  categories,
  onChanged,
}: {
  rows: Customer[];
  categories: string[];
  onChanged: () => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [search, setSearch] = useState("");
  const [fName, setFName] = useState<Filter>(null);
  const [fCountry, setFCountry] = useState<Filter>(null);
  const [fCtype, setFCtype] = useState<Filter>(null);
  const [fCat, setFCat] = useState<Filter>(null);
  const [fBand, setFBand] = useState<Filter>(null);
  const [edit, setEdit] = useState<{ id: number; field: EditField; value: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const nameVals = useMemo(
    () => Array.from(new Set(rows.map((r) => r.name))).sort((a, b) => a.localeCompare(b)),
    [rows],
  );
  const countryVals = useMemo(
    () => Array.from(new Set(rows.map(countryValue))).sort((a, b) => a.localeCompare(b)),
    [rows],
  );
  const ctypeVals = useMemo(() => {
    const present = new Set(rows.map(ctypeValue));
    return ["OEM", "Reseller", "Distributor", "—"].filter((t) => present.has(t));
  }, [rows]);
  const catVals = useMemo(
    () => Array.from(new Set(rows.map(catValue))).sort((a, b) => a.localeCompare(b)),
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
          r.name.toLowerCase().includes(q) ||
          (r.country ?? "").toLowerCase().includes(q) ||
          (r.category ?? "").toLowerCase().includes(q) ||
          (r.ctype ?? "").toLowerCase().includes(q) ||
          (r.domain ?? "").toLowerCase().includes(q) ||
          (r.email ?? "").toLowerCase().includes(q) ||
          (r.phone ?? "").toLowerCase().includes(q)) &&
        (fName === null || fName.has(r.name)) &&
        (fCountry === null || fCountry.has(countryValue(r))) &&
        (fCtype === null || fCtype.has(ctypeValue(r))) &&
        (fCat === null || fCat.has(catValue(r))) &&
        (fBand === null || fBand.has(bandValue(r))),
    );
    const sorted = [...filtered].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "name") cmp = a.name.localeCompare(b.name);
      else if (sortKey === "country") cmp = countryValue(a).localeCompare(countryValue(b));
      else if (sortKey === "ctype") cmp = ctypeValue(a).localeCompare(ctypeValue(b));
      else if (sortKey === "category") cmp = catValue(a).localeCompare(catValue(b));
      else cmp = (BAND_RANK[a.band ?? ""] ?? 9) - (BAND_RANK[b.band ?? ""] ?? 9);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [rows, search, fName, fCountry, fCtype, fCat, fBand, sortKey, sortDir]);

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir("asc");
    }
  };
  const arrow = (k: SortKey) => (sortKey === k ? (sortDir === "asc" ? " ▲" : " ▼") : "");

  const startEdit = (r: Customer, field: EditField) =>
    setEdit({ id: r.id, field, value: (r[field] as string | null) ?? "" });

  const save = async () => {
    if (!edit) return;
    setBusy(true);
    try {
      await apiFetch(`/api/brain/customers/${edit.id}`, {
        method: "PATCH",
        body: JSON.stringify({ [edit.field]: edit.value.trim() || null }),
      });
      setEdit(null);
      onChanged();
    } finally {
      setBusy(false);
    }
  };
  const archive = async (id: number) => {
    await apiFetch(`/api/brain/customers/${id}`, {
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
          placeholder="Search name, location, type, category, website…"
          className="px-3 py-1.5 text-sm rounded-lg border border-ink/15 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 flex-1 min-w-[220px]"
        />
        <span className="text-xs text-ink/45 tabular-nums">
          {view.length}/{rows.length}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="text-sm text-ink/45 py-4">
          No customers yet — add one below or hit “Sync Customers”.
        </p>
      ) : (
        <div className="overflow-auto max-h-[30rem] border border-ink/10 rounded-xl">
          <table className="w-full text-sm min-w-[1060px]">
            <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_rgba(0,0,0,0.06)]">
              <tr className="text-left text-xs font-mono uppercase tracking-wider text-ink/45">
                <Th label={"Customer" + arrow("name")} onSort={() => toggleSort("name")}>
                  <HeaderFilter title="Filter name" values={nameVals} filter={fName} onChange={setFName} />
                </Th>
                <Th label={"Location" + arrow("country")} onSort={() => toggleSort("country")}>
                  <HeaderFilter title="Filter location" values={countryVals} filter={fCountry} onChange={setFCountry} />
                </Th>
                <Th label={"Type" + arrow("ctype")} onSort={() => toggleSort("ctype")}>
                  <HeaderFilter title="Filter type" values={ctypeVals} filter={fCtype} onChange={setFCtype} />
                </Th>
                <Th label={"Category" + arrow("category")} onSort={() => toggleSort("category")}>
                  <HeaderFilter title="Filter category" values={catVals} filter={fCat} onChange={setFCat} />
                </Th>
                <th className="px-3 py-2.5 font-medium">Website</th>
                <th className="px-3 py-2.5 font-medium">Phone</th>
                <th className="px-3 py-2.5 font-medium">Email</th>
                <Th label={"SalesPath" + arrow("band")} onSort={() => toggleSort("band")}>
                  <HeaderFilter
                    title="Filter SalesPath label"
                    values={bandVals}
                    filter={fBand}
                    onChange={setFBand}
                    renderLabel={(v) => (v === "not classified" ? v : "SalesPath " + v)}
                  />
                </Th>
                <th className="px-3 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {view.map((r) => (
                <tr key={r.id} className="border-t border-ink/5 hover:bg-canvas/60 align-top">
                  {/* Name */}
                  <td className="px-3 py-2.5 font-body text-ink">
                    <EditableText
                      r={r}
                      field="name"
                      edit={edit}
                      busy={busy}
                      onStart={startEdit}
                      onChange={(v) => setEdit((e) => (e ? { ...e, value: v } : e))}
                      onSave={save}
                      onCancel={() => setEdit(null)}
                    />
                    {r.manual && (
                      <span className="ml-2 text-[10px] uppercase tracking-wide text-mpower-orange/80 bg-mpower-orange/10 px-1.5 py-0.5 rounded">
                        manual
                      </span>
                    )}
                  </td>
                  {/* Location (country) */}
                  <td className="px-3 py-2.5 text-ink/70 whitespace-nowrap">
                    <EditableText
                      r={r}
                      field="country"
                      placeholder="—"
                      edit={edit}
                      busy={busy}
                      onStart={startEdit}
                      onChange={(v) => setEdit((e) => (e ? { ...e, value: v } : e))}
                      onSave={save}
                      onCancel={() => setEdit(null)}
                    />
                  </td>
                  {/* Type (OEM / Reseller / Distributor) */}
                  <td className="px-3 py-2.5 text-ink/70 whitespace-nowrap">
                    {edit && edit.id === r.id && edit.field === "ctype" ? (
                      <span className="flex items-center gap-1">
                        <select
                          autoFocus
                          value={edit.value}
                          onChange={(e) => setEdit({ ...edit, value: e.target.value })}
                          className="px-2 py-1 text-sm rounded border border-mpower-orange/50 focus:outline-none"
                        >
                          <option value="">—</option>
                          {CTYPES.map((t) => (
                            <option key={t} value={t}>
                              {t}
                            </option>
                          ))}
                        </select>
                        <SaveCancel busy={busy} onSave={save} onCancel={() => setEdit(null)} />
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => startEdit(r, "ctype")}
                        className="group inline-flex items-center gap-1 text-left btn-press"
                        title="Click to edit type"
                      >
                        <CtypePill c={r} />
                        {isLocked(r, "ctype") && <LockDot />}
                        <span className="opacity-0 group-hover:opacity-100 text-ink/30">✎</span>
                      </button>
                    )}
                  </td>
                  {/* Category (constrained to mPower's own categories) */}
                  <td className="px-3 py-2.5 text-ink/70">
                    {edit && edit.id === r.id && edit.field === "category" ? (
                      <span className="flex items-center gap-1">
                        <select
                          autoFocus
                          value={edit.value}
                          onChange={(e) => setEdit({ ...edit, value: e.target.value })}
                          className="px-2 py-1 text-sm rounded border border-mpower-orange/50 focus:outline-none max-w-[200px]"
                        >
                          <option value="">—</option>
                          {categories.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                        <SaveCancel busy={busy} onSave={save} onCancel={() => setEdit(null)} />
                      </span>
                    ) : (
                      <CellButton onClick={() => startEdit(r, "category")} locked={isLocked(r, "category")}>
                        {r.category ?? "—"}
                      </CellButton>
                    )}
                  </td>
                  {/* Website */}
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    {edit && edit.id === r.id && edit.field === "website" ? (
                      <span className="flex items-center gap-1">
                        <input
                          autoFocus
                          value={edit.value}
                          onChange={(e) => setEdit({ ...edit, value: e.target.value })}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void save();
                            if (e.key === "Escape") setEdit(null);
                          }}
                          className="w-44 px-2 py-1 text-sm rounded border border-mpower-orange/50 focus:outline-none"
                        />
                        <SaveCancel busy={busy} onSave={save} onCancel={() => setEdit(null)} />
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5">
                        {r.website ? (
                          <a
                            href={r.website}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-mpower-orange hover:underline"
                          >
                            {r.domain ?? "link"}
                          </a>
                        ) : (
                          <span className="text-ink/35">—</span>
                        )}
                        {r.website_verified === false && (
                          <span
                            className="text-warn-amber text-xs"
                            title="Website could not be confirmed to resolve — kept the discovered URL."
                          >
                            ⚠ unverified
                          </span>
                        )}
                        <button
                          type="button"
                          onClick={() => startEdit(r, "website")}
                          className="text-ink/25 hover:text-ink/60 btn-press"
                          title="Edit website"
                        >
                          ✎
                        </button>
                        {isLocked(r, "website") && <LockDot />}
                      </span>
                    )}
                  </td>
                  {/* Phone (company contact — harvested native or Apollo-enriched) */}
                  <td className="px-3 py-2.5 text-ink/70 whitespace-nowrap">
                    {r.phone ? (
                      <a href={`tel:${r.phone}`} className="hover:text-ink">
                        {r.phone}
                      </a>
                    ) : (
                      <span className="text-ink/35">—</span>
                    )}
                  </td>
                  {/* Email (Apollo + MillionVerifier-verified company contact) */}
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    {r.email ? (
                      <span className="inline-flex items-center gap-1.5">
                        <a href={`mailto:${r.email}`} className="text-mpower-orange hover:underline">
                          {r.email}
                        </a>
                        {r.email_quality === "catch_all" && (
                          <span
                            className="text-warn-amber text-[10px] uppercase tracking-wide"
                            title="Catch-all domain — accepts any address; on the company's own domain."
                          >
                            catch-all
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="text-ink/35">—</span>
                    )}
                  </td>
                  {/* SalesPath band */}
                  <td className="px-3 py-2.5">
                    <BandPill c={r} />
                  </td>
                  {/* Archive */}
                  <td className="px-3 py-2.5 text-right">
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

function LockDot() {
  return (
    <span className="text-[10px] text-mpower-orange/80" title="Manually edited — survives sync">
      • edited
    </span>
  );
}

function SaveCancel({ busy, onSave, onCancel }: { busy: boolean; onSave: () => void; onCancel: () => void }) {
  return (
    <>
      <button type="button" disabled={busy} onClick={onSave} className="text-xs text-ok-green hover:underline btn-press">
        save
      </button>
      <button type="button" onClick={onCancel} className="text-xs text-ink/40 hover:text-ink btn-press">
        ✕
      </button>
    </>
  );
}

function CellButton({
  children,
  onClick,
  locked,
}: {
  children: React.ReactNode;
  onClick: () => void;
  locked: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group inline-flex items-start gap-1 text-left hover:text-ink btn-press"
      title="Click to edit"
    >
      <span>{children}</span>
      {locked && <LockDot />}
      <span className="opacity-0 group-hover:opacity-100 text-ink/30">✎</span>
    </button>
  );
}

function EditableText({
  r,
  field,
  placeholder,
  edit,
  busy,
  onStart,
  onChange,
  onSave,
  onCancel,
}: {
  r: Customer;
  field: EditField;
  placeholder?: string;
  edit: { id: number; field: EditField; value: string } | null;
  busy: boolean;
  onStart: (r: Customer, field: EditField) => void;
  onChange: (v: string) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  if (edit && edit.id === r.id && edit.field === field) {
    return (
      <span className="inline-flex items-center gap-1">
        <input
          autoFocus
          value={edit.value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSave();
            if (e.key === "Escape") onCancel();
          }}
          className="w-40 px-2 py-1 text-sm rounded border border-mpower-orange/50 focus:outline-none"
        />
        <SaveCancel busy={busy} onSave={onSave} onCancel={onCancel} />
      </span>
    );
  }
  const val = (r[field] as string | null) ?? "";
  return (
    <CellButton onClick={() => onStart(r, field)} locked={isLocked(r, field)}>
      {val || <span className="text-ink/35">{placeholder ?? "—"}</span>}
    </CellButton>
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
// the Competitors + Products & Services tables.
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
