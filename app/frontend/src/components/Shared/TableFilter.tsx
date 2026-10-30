"use client";

import { useRef, useState } from "react";
import { createPortal } from "react-dom";

// Shared table primitives — the Google-Sheets-style sortable header + funnel
// (checkbox) column filter used by mPower's Brain sub-tab tables. Extracted here
// (verbatim from the Brain pattern) so the Leads table can reuse the exact same
// UX without disturbing the working Brain copies. A future cleanup can migrate
// CatalogTable/CompetitorTable/CustomerTable onto this shared component.

export type Filter = Set<string> | null; // null = all shown; Set = only those values

export function Th({
  label,
  onSort,
  children,
}: {
  label: string;
  onSort: () => void;
  children?: React.ReactNode;
}) {
  return (
    <th className="px-4 py-3 font-medium whitespace-nowrap">
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

// Funnel button → portaled checkbox popover of the column's distinct values, with
// a search box inside for long lists. Portaled to <body> with position:fixed so it
// is never clipped by the table's overflow:auto scroll container.
export function HeaderFilter({
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
