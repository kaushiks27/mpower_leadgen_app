"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ErrorText } from "@/components/Shared/ui";
import { ApiError, apiFetch } from "@/lib/api";
import {
  BAND_BADGE,
  type LeadgenCustomer,
  type LeadgenLists,
  type RoleGroup,
} from "./leadgenShared";

// CR-1: the modal only ever shows high-confidence customers. These two bands are
// the allow-list; both ON by default. Unticking one narrows to the other; the
// backend enforces this regardless (Unsure/No/blank are never returned).
const PICKER_BANDS = ["Sure", "Likely"] as const;

// Multi-step wizard to scope and kick off a lead-generation run. Selections flow:
// Categories → Type → Country → Customers (live-filtered) → Roles → Scrape.
// On submit POSTs /api/leadgen/generate and hands the job id back to the parent,
// which opens the 6-stage progress modal.
export default function GenerateLeadsPopup({
  onClose,
  onStarted,
}: {
  onClose: () => void;
  onStarted: (jobId: number) => void;
}) {
  const [lists, setLists] = useState<LeadgenLists | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  // Selections.
  const [cats, setCats] = useState<Set<string>>(new Set());
  const [types, setTypes] = useState<Set<string>>(new Set());
  const [country, setCountry] = useState<string>(""); // "" = Worldwide (any)
  // CR-1: SalesPath band filter — both ON by default.
  const [bands, setBands] = useState<Set<string>>(new Set(PICKER_BANDS));
  const [customerIds, setCustomerIds] = useState<Set<number>>(new Set());
  const [roleGroups, setRoleGroups] = useState<Set<string>>(new Set());

  // Live-filtered customers (server-side filter on cats/type/country).
  const [filtered, setFiltered] = useState<LeadgenCustomer[]>([]);
  const [custLoading, setCustLoading] = useState(false);
  // Free-text search over the loaded customer list (name / type / country).
  const [custQ, setCustQ] = useState("");
  const shownCustomers = useMemo(() => {
    const q = custQ.trim().toLowerCase();
    if (!q) return filtered;
    return filtered.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        (c.type ?? "").toLowerCase().includes(q) ||
        (c.country ?? "").toLowerCase().includes(q),
    );
  }, [filtered, custQ]);

  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch("/api/leadgen/lists", { method: "GET" });
        if (!res.ok) throw new ApiError(res.status, "Could not load options.");
        const data = (await res.json()) as LeadgenLists;
        setLists(data);
        setFiltered(data.customers);
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "Could not load options.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Re-query the customer list whenever the upstream filters change.
  const refetchCustomers = useCallback(async () => {
    setCustLoading(true);
    try {
      const params = new URLSearchParams();
      if (cats.size > 0) params.set("categories", Array.from(cats).join(","));
      if (types.size > 0) params.set("type", Array.from(types).join(","));
      if (country.trim()) params.set("country", country.trim());
      // CR-1: always send the band allow-list (defaults to both).
      params.set("bands", Array.from(bands).join(","));
      const res = await apiFetch(`/api/leadgen/customers?${params.toString()}`, { method: "GET" });
      if (!res.ok) throw new ApiError(res.status, "Could not load customers.");
      const data = (await res.json()) as LeadgenCustomer[];
      setFiltered(data);
      // Drop any selected customers no longer in the filtered set.
      setCustomerIds((prev) => {
        const allowed = new Set(data.map((c) => c.id));
        const next = new Set<number>();
        prev.forEach((id) => {
          if (allowed.has(id)) next.add(id);
        });
        return next;
      });
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load customers.");
    } finally {
      setCustLoading(false);
    }
  }, [cats, types, country, bands]);

  // Refetch on filter change (skip the very first render — initial list already set).
  const filterKey = useMemo(
    () =>
      `${Array.from(cats).sort().join(",")}|${Array.from(types).sort().join(",")}|${country}|${Array.from(bands).sort().join(",")}`,
    [cats, types, country, bands],
  );
  const [primed, setPrimed] = useState(false);
  useEffect(() => {
    if (!primed) {
      setPrimed(true);
      return;
    }
    void refetchCustomers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  const toggleStr = (set: Set<string>, setFn: (s: Set<string>) => void, v: string) => {
    const next = new Set(set);
    if (next.has(v)) next.delete(v);
    else next.add(v);
    setFn(next);
  };
  const toggleNum = (set: Set<number>, setFn: (s: Set<number>) => void, v: number) => {
    const next = new Set(set);
    if (next.has(v)) next.delete(v);
    else next.add(v);
    setFn(next);
  };

  const canSubmit = customerIds.size > 0 && roleGroups.size > 0 && !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setErr("");
    setSubmitting(true);
    try {
      const res = await apiFetch("/api/leadgen/generate", {
        method: "POST",
        body: JSON.stringify({
          categories: Array.from(cats),
          types: Array.from(types),
          country: country.trim() || null,
          customer_ids: Array.from(customerIds),
          role_groups: Array.from(roleGroups),
        }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new ApiError(res.status, b.detail ?? "Could not start generation.");
      }
      const data = (await res.json()) as { id: number };
      onStarted(data.id);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not start generation.");
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 bg-ink/40 overflow-y-auto">
      <div className="bg-surface rounded-2xl shadow-xl border border-ink/10 w-full max-w-2xl my-8 flex flex-col max-h-[88vh]">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 p-6 pb-4 border-b border-ink/10">
          <div>
            <h3 className="font-heading text-lg font-semibold text-ink">Generate Leads</h3>
            <p className="text-xs font-body text-ink/50 mt-0.5">
              Scope a scrape run — pick which customers and which decision-maker roles to chase.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-ink/40 hover:text-ink btn-press text-lg leading-none px-2"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {loading ? (
            <p className="text-sm text-ink/50">Loading options…</p>
          ) : !lists ? (
            <ErrorText>{err || "Could not load options."}</ErrorText>
          ) : (
            <>
              {/* 1. Categories */}
              <SectionCard
                step={1}
                title="Categories"
                hint="Filter customers by the product categories they buy."
                action={
                  <SelectAll
                    all={cats.size === lists.categories.length && lists.categories.length > 0}
                    onSelectAll={() => setCats(new Set(lists.categories))}
                    onClear={() => setCats(new Set())}
                  />
                }
              >
                <div className="space-y-4">
                  <CatGroup
                    label="Products"
                    items={lists.categories_grouped?.product ?? []}
                    checked={(v) => cats.has(v)}
                    onToggle={(v) => toggleStr(cats, setCats, v)}
                  />
                  <CatGroup
                    label="Services"
                    items={lists.categories_grouped?.service ?? []}
                    checked={(v) => cats.has(v)}
                    onToggle={(v) => toggleStr(cats, setCats, v)}
                  />
                </div>
              </SectionCard>

              {/* 2. Type */}
              <SectionCard
                step={2}
                title="Type"
                hint="OEM, Reseller, or Distributor."
                action={
                  <SelectAll
                    all={types.size === lists.types.length && lists.types.length > 0}
                    label="All"
                    onSelectAll={() => setTypes(new Set(lists.types))}
                    onClear={() => setTypes(new Set())}
                  />
                }
              >
                <CheckGrid
                  items={lists.types}
                  checked={(v) => types.has(v)}
                  onToggle={(v) => toggleStr(types, setTypes, v)}
                />
              </SectionCard>

              {/* 3. Country */}
              <SectionCard step={3} title="Country" hint="Narrow to one country, or leave worldwide.">
                <select
                  value={country}
                  onChange={(e) => setCountry(e.target.value)}
                  className="w-full max-w-xs px-3 py-2 text-sm rounded-xl border border-ink/15 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 text-ink/80"
                >
                  <option value="">Worldwide (any)</option>
                  {lists.countries.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </SectionCard>

              {/* 4. Customers (live-filtered) */}
              <SectionCard
                step={4}
                title="Customers"
                hint="Only SalesPath Sure & Likely companies are shown. Pick who to source contacts at."
                action={
                  <div className="flex items-center gap-2">
                    {custLoading && <span className="text-xs text-ink/40">updating…</span>}
                    <button
                      type="button"
                      onClick={() =>
                        setCustomerIds((prev) => {
                          const next = new Set(prev);
                          shownCustomers.forEach((c) => next.add(c.id));
                          return next;
                        })
                      }
                      className="text-xs text-ink/55 hover:text-ink btn-press"
                    >
                      {custQ.trim() ? "Select all shown" : "Select all customers"}
                    </button>
                    <span className="text-ink/20">·</span>
                    <button
                      type="button"
                      onClick={() => setCustomerIds(new Set())}
                      className="text-xs text-mpower-orange hover:underline btn-press"
                    >
                      Clear
                    </button>
                  </div>
                }
              >
                {/* CR-1: SalesPath band filter — both ON by default. */}
                <div className="flex items-center gap-3 mb-2.5">
                  <span className="text-xs text-ink/45">SalesPath:</span>
                  {PICKER_BANDS.map((b) => {
                    const badge = BAND_BADGE[b];
                    const on = bands.has(b);
                    return (
                      <label
                        key={b}
                        className="flex items-center gap-1.5 text-sm cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() => toggleStr(bands, setBands, b)}
                          className="accent-mpower-orange"
                        />
                        <span className={"px-1.5 py-0.5 rounded-full text-xs " + badge.cls}>
                          {badge.label}
                        </span>
                      </label>
                    );
                  })}
                </div>
                {filtered.length > 0 && (
                  <input
                    value={custQ}
                    onChange={(e) => setCustQ(e.target.value)}
                    placeholder="Search customers by name, type, or country…"
                    className="w-full mb-2 px-3 py-1.5 text-sm rounded-lg border border-ink/15 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30"
                  />
                )}
                {filtered.length === 0 ? (
                  <p className="text-sm text-ink/45 py-2">
                    No customers match these filters. Loosen the categories, type, or country.
                  </p>
                ) : shownCustomers.length === 0 ? (
                  <p className="text-sm text-ink/45 py-2">No customers match “{custQ.trim()}”.</p>
                ) : (
                  <div className="max-h-56 overflow-auto rounded-xl border border-ink/10 divide-y divide-ink/5">
                    {shownCustomers.map((c) => (
                      <label
                        key={c.id}
                        className="flex items-center gap-2.5 px-3 py-2 text-sm cursor-pointer hover:bg-canvas/60"
                      >
                        <input
                          type="checkbox"
                          checked={customerIds.has(c.id)}
                          onChange={() => toggleNum(customerIds, setCustomerIds, c.id)}
                          className="accent-mpower-orange shrink-0"
                        />
                        <span className="font-body text-ink truncate">{c.name}</span>
                        {c.band && BAND_BADGE[c.band] && (
                          <span
                            className={
                              "text-xs px-1.5 py-0.5 rounded-full shrink-0 " +
                              BAND_BADGE[c.band].cls
                            }
                          >
                            {BAND_BADGE[c.band].label}
                          </span>
                        )}
                        {c.type && (
                          <span className="text-xs px-1.5 py-0.5 rounded-full bg-ink/[0.06] text-ink/65 shrink-0">
                            {c.type}
                          </span>
                        )}
                        <span className="text-xs text-ink/45 ml-auto shrink-0">{c.country || "—"}</span>
                      </label>
                    ))}
                  </div>
                )}
                <p className="text-xs text-ink/45 mt-1.5 tabular-nums">
                  {customerIds.size} of {filtered.length} selected
                  {custQ.trim() && shownCustomers.length !== filtered.length
                    ? ` · showing ${shownCustomers.length}`
                    : ""}
                </p>
              </SectionCard>

              {/* 5. Roles */}
              <SectionCard
                step={5}
                title="Roles"
                hint="Which decision-makers to look for at each customer."
                action={
                  <SelectAll
                    all={roleGroups.size === lists.roles.length && lists.roles.length > 0}
                    onSelectAll={() => setRoleGroups(new Set(lists.roles.map((r) => r.group)))}
                    onClear={() => setRoleGroups(new Set())}
                  />
                }
              >
                {lists.roles.length === 0 ? (
                  <p className="text-sm text-ink/45 py-2">No roles configured.</p>
                ) : (
                  <div className="space-y-1.5">
                    {lists.roles.map((g) => (
                      <RoleRow
                        key={g.group}
                        group={g}
                        checked={roleGroups.has(g.group)}
                        onToggle={() => toggleStr(roleGroups, setRoleGroups, g.group)}
                      />
                    ))}
                  </div>
                )}
                <p className="text-xs text-ink/45 mt-1.5 tabular-nums">{roleGroups.size} selected</p>
              </SectionCard>
            </>
          )}

          {err && lists && <ErrorText>{err}</ErrorText>}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 p-6 pt-4 border-t border-ink/10">
          <p className="text-xs text-ink/45">
            {customerIds.size === 0 || roleGroups.size === 0
              ? "Pick at least one customer and one role to start."
              : `${customerIds.size} customer(s) · ${roleGroups.size} role(s)`}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 rounded-xl border border-ink/15 font-body text-ink/70 hover:bg-canvas btn-press"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={!canSubmit}
              className="px-5 py-2.5 bg-mpower-orange text-white font-heading font-semibold rounded-xl hover:bg-mpower-orange/90 btn-press disabled:opacity-50"
            >
              {submitting ? "Starting…" : "Scrape Leads"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function SectionCard({
  step,
  title,
  hint,
  action,
  children,
}: {
  step: number;
  title: string;
  hint: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-ink/10 p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="w-6 h-6 shrink-0 rounded-full bg-mpower-orange/10 text-mpower-orange flex items-center justify-center text-xs font-semibold">
            {step}
          </span>
          <div className="min-w-0">
            <p className="font-heading text-sm font-semibold text-ink">{title}</p>
            <p className="text-xs text-ink/45">{hint}</p>
          </div>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function SelectAll({
  all,
  label = "Select all",
  onSelectAll,
  onClear,
}: {
  all: boolean;
  label?: string;
  onSelectAll: () => void;
  onClear: () => void;
}) {
  return (
    <div className="flex items-center gap-2 shrink-0">
      <button
        type="button"
        onClick={all ? onClear : onSelectAll}
        className="text-xs text-ink/55 hover:text-ink btn-press"
      >
        {all ? "Clear" : label}
      </button>
    </div>
  );
}

function CatGroup({
  label,
  items,
  checked,
  onToggle,
}: {
  label: string;
  items: string[];
  checked: (v: string) => boolean;
  onToggle: (v: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-ink/40 mb-1.5">{label}</p>
      <CheckGrid items={items} checked={checked} onToggle={onToggle} />
    </div>
  );
}

function CheckGrid({
  items,
  checked,
  onToggle,
}: {
  items: string[];
  checked: (v: string) => boolean;
  onToggle: (v: string) => void;
}) {
  if (items.length === 0) return <p className="text-sm text-ink/45">Nothing available.</p>;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
      {items.map((v) => (
        <label
          key={v}
          className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-sm cursor-pointer hover:bg-canvas/60 border border-transparent hover:border-ink/10"
        >
          <input
            type="checkbox"
            checked={checked(v)}
            onChange={() => onToggle(v)}
            className="accent-mpower-orange shrink-0"
          />
          <span className="font-body text-ink/80 truncate">{v}</span>
        </label>
      ))}
    </div>
  );
}

function RoleRow({
  group,
  checked,
  onToggle,
}: {
  group: RoleGroup;
  checked: boolean;
  onToggle: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-ink/10">
      <div className="flex items-center gap-2.5 px-3 py-2">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="accent-mpower-orange shrink-0"
        />
        <span className="font-body text-sm text-ink/85">{group.group}</span>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="ml-auto text-xs text-ink/45 hover:text-ink btn-press"
        >
          {open ? "hide" : `${group.titles.length} title(s)`}
        </button>
      </div>
      {open && (
        <div className="px-3 pb-2.5 flex flex-wrap gap-1.5 border-t border-ink/5 pt-2">
          {group.titles.length === 0 ? (
            <span className="text-xs text-ink/40">No title variants.</span>
          ) : (
            group.titles.map((t) => (
              <span key={t} className="px-2 py-0.5 rounded-full text-xs font-body bg-ink/[0.06] text-ink/65">
                {t}
              </span>
            ))
          )}
        </div>
      )}
    </div>
  );
}
