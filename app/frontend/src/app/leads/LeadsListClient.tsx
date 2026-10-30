"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { ErrorText } from "@/components/Shared/ui";
import { HeaderFilter, Th, type Filter } from "@/components/Shared/TableFilter";
import JobProgressPopup from "@/components/Shared/JobProgressPopup";
import GenerateLeadsPopup from "./GenerateLeadsPopup";
import GenerateLeadsProgressPopup from "./GenerateLeadsProgressPopup";
import {
  STAGE_LABEL,
  STAGES,
  emailStatusBadge,
  formatINR,
  type Lead,
  type LeadDetail,
  type Stage,
} from "./types";

// Inline-editable potential-value cell (S-7). The value is exact whole INR — no
// decimals, never AI-set. Typing a number + Enter/blur PATCHes the lead; clearing
// the box sends clear_value so the pipeline treats it as unset (sorts last).
function ValueCell({
  lead,
  onChanged,
}: {
  lead: Lead;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const begin = () => {
    setDraft(lead.value_inr != null ? String(lead.value_inr) : "");
    setEditing(true);
  };

  const commit = async () => {
    const raw = draft.trim();
    const next = raw === "" ? null : Math.max(0, Math.floor(Number(raw) || 0));
    setEditing(false);
    // No change -> skip the round-trip.
    if (next === (lead.value_inr ?? null)) return;
    setSaving(true);
    try {
      await apiFetch(`/api/leads/${lead.id}`, {
        method: "PATCH",
        body: JSON.stringify(
          next === null ? { clear_value: true } : { value_inr: next },
        ),
      });
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <input
        autoFocus
        type="number"
        min={0}
        value={draft}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === "Enter") void commit();
          if (e.key === "Escape") setEditing(false);
        }}
        placeholder="INR"
        className="w-28 px-2 py-1 rounded-lg border border-mpower-orange/40 font-body text-ink text-sm focus:outline-none focus:ring-2 focus:ring-mpower-orange/30"
      />
    );
  }
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        begin();
      }}
      className="text-ink/75 hover:text-mpower-orange btn-press tabular-nums"
      title="Click to set potential value"
    >
      {saving ? "…" : formatINR(lead.value_inr)}
    </button>
  );
}

function EmailStatusBadge({ status }: { status: string | null }) {
  const b = emailStatusBadge(status);
  if (!b) return <span className="text-ink/40">—</span>;
  return (
    <span
      className={"px-2 py-0.5 rounded-full text-xs font-body font-medium " + b.cls}
    >
      {b.label}
    </span>
  );
}

// Inline-editable icebreaker cell (S-7). The AI writes it; the user can fix the
// wording here. Click to edit, Enter/blur saves (blank clears), Esc cancels.
// Exported so the per-campaign lead tab reuses the exact same editor.
export function IcebreakerCell({
  lead,
  onChanged,
}: {
  lead: Lead;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const begin = () => {
    setDraft(lead.icebreaker ?? "");
    setEditing(true);
  };
  const commit = async () => {
    const next = draft.trim();
    setEditing(false);
    if (next === (lead.icebreaker ?? "")) return;
    setSaving(true);
    try {
      await apiFetch(`/api/leads/${lead.id}`, {
        method: "PATCH",
        body: JSON.stringify({ icebreaker: next }),
      });
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <textarea
        autoFocus
        rows={2}
        value={draft}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void commit();
          }
          if (e.key === "Escape") setEditing(false);
        }}
        placeholder="Write an icebreaker…"
        className="w-56 px-2 py-1 rounded-lg border border-mpower-orange/40 font-body text-ink text-xs focus:outline-none focus:ring-2 focus:ring-mpower-orange/30"
      />
    );
  }
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        begin();
      }}
      title={lead.icebreaker ?? "Click to write an icebreaker"}
      className="text-left text-ink/60 hover:text-mpower-orange btn-press max-w-[220px] truncate block"
    >
      {saving ? "…" : (lead.icebreaker ?? "—")}
    </button>
  );
}

function StageBadge({ stage }: { stage: Stage }) {
  return (
    <span className="px-2 py-0.5 rounded-full text-xs font-body font-medium bg-mpower-orange/10 text-mpower-orange">
      {STAGE_LABEL[stage]}
    </span>
  );
}

export function FlagBadges({ lead }: { lead: Lead }) {
  const flags: { on: boolean; label: string; cls: string }[] = [
    { on: lead.bounced, label: "Bounced", cls: "bg-err-red/10 text-err-red" },
    {
      on: lead.unsubscribed,
      label: "Unsub",
      cls: "bg-warn-amber/15 text-warn-amber",
    },
    {
      on: lead.not_interested,
      label: "Not interested",
      cls: "bg-ink/10 text-ink/55",
    },
    {
      on: lead.suppressed,
      label: "Suppressed",
      cls: "border border-err-red/40 text-err-red",
    },
  ];
  const active = flags.filter((f) => f.on);
  if (active.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {active.map((f) => (
        <span
          key={f.label}
          className={"px-2 py-0.5 rounded-full text-xs font-body font-medium " + f.cls}
        >
          {f.label}
        </span>
      ))}
    </span>
  );
}

// Combined active-flag label for a lead (used by the Flags column sort + filter).
function flagsVal(l: Lead): string {
  const f: string[] = [];
  if (l.bounced) f.push("Bounced");
  if (l.unsubscribed) f.push("Unsub");
  if (l.not_interested) f.push("Not interested");
  if (l.suppressed) f.push("Suppressed");
  return f.length ? f.join(" + ") : "—";
}

// Per-column sort + funnel-filter config — one entry per visible Leads column, in
// render order. `sortVal` drives click-to-sort; `filterVal` is the discrete value
// shown in the funnel checkbox dropdown; `renderLabel` prettifies that value.
type LeadCol = {
  id: string;
  label: string;
  sortVal: (l: Lead) => string | number;
  filterVal: (l: Lead) => string;
  renderLabel?: (v: string) => string;
};

const LEAD_COLUMNS: LeadCol[] = [
  { id: "name", label: "Name", sortVal: (l) => l.full_name.toLowerCase(), filterVal: (l) => l.full_name },
  { id: "company", label: "Company", sortVal: (l) => (l.company_name ?? "").toLowerCase(), filterVal: (l) => l.company_name ?? "—" },
  // CR-6: structured taxonomy carried from the originating customer.
  { id: "category", label: "Category", sortVal: (l) => (l.category ?? "").toLowerCase(), filterVal: (l) => l.category ?? "—" },
  { id: "ctype", label: "Type", sortVal: (l) => (l.customer_type ?? "").toLowerCase(), filterVal: (l) => l.customer_type ?? "—" },
  { id: "country", label: "Country", sortVal: (l) => (l.location ?? "").toLowerCase(), filterVal: (l) => l.location ?? "—" },
  { id: "campaign", label: "Campaign", sortVal: (l) => (l.campaign_name ?? "").toLowerCase(), filterVal: (l) => l.campaign_name ?? "—" },
  { id: "owner", label: "Campaign Owner", sortVal: (l) => (l.campaign_owner ?? "").toLowerCase(), filterVal: (l) => l.campaign_owner ?? "—" },
  { id: "value", label: "Value (₹)", sortVal: (l) => l.value_inr ?? -1, filterVal: (l) => (l.value_inr != null ? String(l.value_inr) : "—"), renderLabel: (v) => (v === "—" ? "—" : formatINR(Number(v))) },
  { id: "title", label: "Title", sortVal: (l) => (l.title ?? "").toLowerCase(), filterVal: (l) => l.title ?? "—" },
  { id: "email", label: "Email", sortVal: (l) => (l.email ?? "").toLowerCase(), filterVal: (l) => l.email ?? "—" },
  { id: "verify", label: "Verify", sortVal: (l) => l.email_status ?? "", filterVal: (l) => l.email_status ?? "—", renderLabel: (v) => (v === "—" ? "—" : emailStatusBadge(v)?.label ?? v) },
  { id: "phone", label: "Phone", sortVal: (l) => l.phone ?? "", filterVal: (l) => l.phone ?? "—" },
  { id: "linkedin", label: "LinkedIn", sortVal: (l) => (l.linkedin_url ? 0 : 1), filterVal: (l) => (l.linkedin_url ? "Has LinkedIn" : "—") },
  { id: "icebreaker", label: "Icebreaker", sortVal: (l) => (l.icebreaker ? 0 : 1), filterVal: (l) => (l.icebreaker ? "Has icebreaker" : "—") },
  { id: "stage", label: "Stage", sortVal: (l) => STAGES.indexOf(l.stage), filterVal: (l) => l.stage, renderLabel: (v) => STAGE_LABEL[v as Stage] ?? v },
  { id: "flags", label: "Flags", sortVal: (l) => flagsVal(l), filterVal: (l) => flagsVal(l) },
];

export default function LeadsListClient() {
  const [rows, setRows] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [stage, setStage] = useState<"" | Stage>("");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const { role } = useSession();
  const isAdmin = role === "admin";

  // Client-side sort + per-column funnel filters over the loaded rows (the server
  // already applied the stage dropdown + the top search box). Mirrors the
  // mPower-Brain sub-tab tables.
  const [sortKey, setSortKey] = useState<string>("");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [filters, setFilters] = useState<Record<string, Filter>>({});

  const distinct = useMemo(() => {
    const m: Record<string, string[]> = {};
    for (const c of LEAD_COLUMNS) {
      m[c.id] = Array.from(new Set(rows.map(c.filterVal))).sort((a, b) => {
        if (c.id === "value") {
          if (a === "—") return 1;
          if (b === "—") return -1;
          return (Number(a) || 0) - (Number(b) || 0);
        }
        return a.localeCompare(b);
      });
    }
    return m;
  }, [rows]);

  const view = useMemo(() => {
    let out = rows.filter((l) =>
      LEAD_COLUMNS.every((c) => {
        const f = filters[c.id];
        return f == null || f.has(c.filterVal(l));
      }),
    );
    if (sortKey) {
      const col = LEAD_COLUMNS.find((c) => c.id === sortKey);
      if (col) {
        out = [...out].sort((a, b) => {
          const va = col.sortVal(a);
          const vb = col.sortVal(b);
          const cmp =
            typeof va === "number" && typeof vb === "number"
              ? va - vb
              : String(va).localeCompare(String(vb));
          return sortDir === "asc" ? cmp : -cmp;
        });
      }
    }
    return out;
  }, [rows, filters, sortKey, sortDir]);

  const toggleSort = (k: string) => {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir("asc");
    }
  };
  const arrow = (k: string) => (sortKey === k ? (sortDir === "asc" ? " ▲" : " ▼") : "");

  // Generate-Leads wizard + 6-stage progress modal state.
  const [wizardOpen, setWizardOpen] = useState(false);
  const [genJobId, setGenJobId] = useState<number | null>(null);
  const [progressOpen, setProgressOpen] = useState(false);

  // CR-2: bulk "Create Icebreaker" over selected verified leads (relocated here
  // from the campaign page). `selected` holds lead ids; the action launches a
  // background job and opens the shared progress popup.
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [iceJobId, setIceJobId] = useState<number | null>(null);
  const [iceOpen, setIceOpen] = useState(false);
  const [iceBusy, setIceBusy] = useState(false);

  const toggleSel = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // Only verified (SalesPath Sure/Likely) leads are icebreaker-eligible.
  const eligibleSelected = useMemo(
    () =>
      view.filter(
        (l) =>
          selected.has(l.id) &&
          (l.email_status === "valid" || l.email_status === "catch_all"),
      ),
    [view, selected],
  );

  const createIcebreakers = async () => {
    const ids = eligibleSelected.map((l) => l.id);
    if (ids.length === 0 || iceBusy) return;
    setIceBusy(true);
    setErr("");
    try {
      const res = await apiFetch("/api/leads/icebreaker", {
        method: "POST",
        body: JSON.stringify({ lead_ids: ids }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new ApiError(res.status, payload.detail ?? "Could not start.");
      }
      setIceJobId((payload as { id: number }).id);
      setIceOpen(true);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not start.");
    } finally {
      setIceBusy(false);
    }
  };

  const load = useCallback(async () => {
    setErr("");
    const params = new URLSearchParams();
    if (stage) params.set("stage", stage);
    if (q.trim()) params.set("q", q.trim());
    try {
      const res = await apiFetch(`/api/leads?${params.toString()}`, { method: "GET" });
      if (!res.ok) throw new ApiError(res.status, "Could not load leads.");
      setRows((await res.json()) as Lead[]);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load leads.");
    } finally {
      setLoading(false);
    }
  }, [stage, q]);

  useEffect(() => {
    void load();
  }, [load]);

  // Reattach to an in-flight generation job on mount.
  useEffect(() => {
    void (async () => {
      try {
        const r = await apiFetch("/api/leadgen/active", { method: "GET" });
        if (r.ok) {
          const data = (await r.json()) as { job: { id: number } | null };
          if (data.job) {
            setGenJobId(data.job.id);
            setProgressOpen(true);
          }
        }
      } catch {
        /* ignore — nothing in flight */
      }
    })();
  }, []);

  const pauseGen = async () => {
    try {
      await apiFetch("/api/leadgen/pause", { method: "POST", body: JSON.stringify({}) });
    } catch {
      /* the popup keeps polling; it will reflect the paused state */
    }
  };

  // Cancel = permanently kill the in-flight/paused run so the next Generate starts
  // fresh (no resume). Clears the local handle + closes the modal.
  const cancelGen = async () => {
    try {
      await apiFetch("/api/leadgen/cancel", { method: "POST", body: JSON.stringify({}) });
    } catch {
      /* even if the call fails, drop the local handle so the user can retry */
    }
    setGenJobId(null);
    setProgressOpen(false);
  };

  // Resume = re-POST generate (backend resumes the paused run). Falls back to the
  // existing job id if the response shape is unexpected.
  const resumeGen = async () => {
    try {
      const res = await apiFetch("/api/leadgen/generate", {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (res.ok) {
        const data = (await res.json()) as { id?: number };
        if (typeof data.id === "number") setGenJobId(data.id);
      }
    } catch {
      /* the popup keeps polling the current job id */
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={stage}
          onChange={(e) => setStage(e.target.value as "" | Stage)}
          className="px-3 py-2 rounded-xl border border-ink/15 text-sm font-body text-ink btn-press focus:outline-none focus:ring-2 focus:ring-mpower-orange/30"
        >
          <option value="">All stages</option>
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {STAGE_LABEL[s]}
            </option>
          ))}
        </select>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search name, company, email…"
          className="flex-1 min-w-[200px] px-4 py-2 rounded-xl border border-ink/15 text-sm font-body text-ink placeholder:text-ink/30 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 btn-press"
        />
        <span className="text-xs text-ink/40 tabular-nums">
          {view.length === rows.length
            ? `${rows.length} lead${rows.length === 1 ? "" : "s"}`
            : `${view.length} / ${rows.length} leads`}
        </span>
        {isAdmin && (
          <>
            {selected.size > 0 && (
              <button
                type="button"
                onClick={createIcebreakers}
                disabled={iceBusy || eligibleSelected.length === 0}
                title={
                  eligibleSelected.length === 0
                    ? "Select verified (SalesPath Sure/Likely) leads to write icebreakers"
                    : undefined
                }
                className="px-4 py-2 rounded-xl border border-mpower-orange/40 text-mpower-orange font-heading font-semibold text-sm hover:bg-mpower-orange/10 btn-press disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {iceBusy
                  ? "Starting…"
                  : `Create Icebreaker (${eligibleSelected.length})`}
              </button>
            )}
            {genJobId !== null && !progressOpen && (
              <button
                type="button"
                onClick={() => setProgressOpen(true)}
                className="text-sm font-body text-mpower-orange hover:underline btn-press px-2"
              >
                View progress
              </button>
            )}
            <button
              type="button"
              onClick={() => setWizardOpen(true)}
              className="px-5 py-2 bg-mpower-orange text-white font-heading font-semibold text-sm rounded-xl hover:bg-mpower-orange/90 btn-press"
            >
              Generate Leads
            </button>
          </>
        )}
      </div>

      {loading ? (
        <p className="text-sm text-ink/50">Loading…</p>
      ) : err ? (
        <ErrorText>{err}</ErrorText>
      ) : rows.length === 0 ? (
        <div className="bg-surface border border-ink/10 rounded-2xl p-10 text-center">
          <p className="text-sm text-ink/45">
            No leads yet. Open a campaign and click Generate Leads to start.
          </p>
        </div>
      ) : (
        <div className="bg-surface border border-ink/10 rounded-2xl overflow-auto max-h-[34rem]">
          <table className="w-full text-sm min-w-[1500px]">
            <thead className="sticky top-0 z-10 bg-surface text-left text-xs font-mono uppercase tracking-wider text-ink/40 shadow-[0_1px_0_rgba(0,0,0,0.08)]">
              <tr>
                {isAdmin && (
                  <th className="px-4 py-3 w-10">
                    <input
                      type="checkbox"
                      aria-label="Select all shown"
                      className="accent-mpower-orange"
                      checked={view.length > 0 && view.every((l) => selected.has(l.id))}
                      onChange={(e) =>
                        setSelected((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) view.forEach((l) => next.add(l.id));
                          else view.forEach((l) => next.delete(l.id));
                          return next;
                        })
                      }
                    />
                  </th>
                )}
                {LEAD_COLUMNS.map((c) => (
                  <Th key={c.id} label={c.label + arrow(c.id)} onSort={() => toggleSort(c.id)}>
                    <HeaderFilter
                      title={`Filter ${c.label}`}
                      values={distinct[c.id] ?? []}
                      filter={filters[c.id] ?? null}
                      onChange={(f) => setFilters((prev) => ({ ...prev, [c.id]: f }))}
                      renderLabel={c.renderLabel}
                    />
                  </Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.map((l) => (
                <tr
                  key={l.id}
                  onClick={() => setOpenId(l.id)}
                  className="border-b border-ink/5 last:border-0 hover:bg-canvas/60 cursor-pointer btn-press"
                >
                  {isAdmin && (
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        className="accent-mpower-orange"
                        checked={selected.has(l.id)}
                        onChange={() => toggleSel(l.id)}
                      />
                    </td>
                  )}
                  <td className="px-4 py-3 font-body text-ink font-medium whitespace-nowrap">
                    {l.full_name}
                  </td>
                  <td className="px-4 py-3 text-ink/70 whitespace-nowrap">{l.company_name ?? "—"}</td>
                  <td className="px-4 py-3 text-ink/70 whitespace-nowrap">{l.category ?? "—"}</td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {l.customer_type ? (
                      <span className="px-2 py-0.5 rounded-full text-xs font-body bg-ink/[0.06] text-ink/65">
                        {l.customer_type}
                      </span>
                    ) : (
                      <span className="text-ink/40">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-ink/70 whitespace-nowrap">{l.location ?? "—"}</td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {l.campaign_name ? (
                      <span className="px-2 py-0.5 rounded-full text-xs font-body font-medium bg-ink/8 text-ink/70">
                        {l.campaign_name}
                      </span>
                    ) : (
                      <span className="text-ink/40">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-ink/70 whitespace-nowrap">
                    {l.campaign_owner ?? <span className="text-ink/40">—</span>}
                  </td>
                  <td
                    className="px-4 py-3 whitespace-nowrap"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <ValueCell lead={l} onChanged={load} />
                  </td>
                  <td className="px-4 py-3 text-ink/70 whitespace-nowrap">{l.title ?? "—"}</td>
                  <td className="px-4 py-3 text-ink/70 whitespace-nowrap">{l.email ?? "—"}</td>
                  <td className="px-4 py-3 whitespace-nowrap"><EmailStatusBadge status={l.email_status} /></td>
                  <td className="px-4 py-3 text-ink/70 whitespace-nowrap">{l.phone ?? "—"}</td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {l.linkedin_url ? (
                      <a
                        href={l.linkedin_url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-mpower-orange hover:underline btn-press"
                      >
                        view
                      </a>
                    ) : (
                      <span className="text-ink/40">—</span>
                    )}
                  </td>
                  <td
                    className="px-4 py-3"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <IcebreakerCell lead={l} onChanged={load} />
                  </td>
                  <td className="px-4 py-3"><StageBadge stage={l.stage} /></td>
                  <td className="px-4 py-3"><FlagBadges lead={l} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openId !== null && (
        <LeadDetailModal id={openId} onClose={() => setOpenId(null)} onChanged={load} />
      )}

      {wizardOpen && (
        <GenerateLeadsPopup
          onClose={() => setWizardOpen(false)}
          onStarted={(jobId) => {
            setWizardOpen(false);
            setGenJobId(jobId);
            setProgressOpen(true);
          }}
        />
      )}

      {genJobId !== null && progressOpen && (
        <GenerateLeadsProgressPopup
          jobId={genJobId}
          onClose={() => setProgressOpen(false)}
          onDone={() => void load()}
          onPause={pauseGen}
          onResume={resumeGen}
          onCancel={cancelGen}
        />
      )}

      {iceJobId !== null && iceOpen && (
        <JobProgressPopup
          jobId={iceJobId}
          onClose={() => setIceOpen(false)}
          onDone={() => {
            setSelected(new Set());
            void load();
          }}
        />
      )}
    </div>
  );
}

function LeadDetailModal({
  id,
  onClose,
  onChanged,
}: {
  id: number;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/leads/${id}`, { method: "GET" });
      if (!res.ok) throw new ApiError(res.status, "Could not load lead.");
      setLead((await res.json()) as LeadDetail);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load lead.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const patch = async (body: Record<string, unknown>) => {
    await apiFetch(`/api/leads/${id}`, { method: "PATCH", body: JSON.stringify(body) });
    await load();
    onChanged();
  };

  return (
    <div
      className="fixed inset-0 z-40 bg-ink/40 flex items-start justify-center p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-surface rounded-2xl shadow-xl w-full max-w-lg mt-16 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        {err ? (
          <ErrorText>{err}</ErrorText>
        ) : !lead ? (
          <p className="text-sm text-ink/50">Loading…</p>
        ) : (
          <div className="space-y-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-heading text-xl font-semibold text-ink">
                  {lead.full_name}
                </h2>
                <p className="text-sm text-ink/55">
                  {[lead.title, lead.company_name, lead.location]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="text-ink/40 hover:text-ink btn-press text-sm"
              >
                Close
              </button>
            </div>

            <div className="text-sm text-ink/70 space-y-1">
              {lead.email ? (
                <p className="flex items-center gap-2">
                  ✉️ {lead.email} <EmailStatusBadge status={lead.email_status} />
                </p>
              ) : null}
              {lead.phone ? <p>📞 {lead.phone}</p> : null}
              {lead.linkedin_url ? (
                <p className="truncate">
                  🔗{" "}
                  <a
                    href={lead.linkedin_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-mpower-orange hover:underline btn-press"
                  >
                    {lead.linkedin_url}
                  </a>
                </p>
              ) : null}
              {lead.icebreaker ? (
                <p className="italic text-ink/60">“{lead.icebreaker}”</p>
              ) : null}
              {lead.campaign_owner ? (
                <p>👤 Owner: {lead.campaign_owner}</p>
              ) : null}
              <p>💰 Value: {formatINR(lead.value_inr)}</p>
              <p className="flex items-center gap-2">
                Stage: <StageBadge stage={lead.stage} /> <FlagBadges lead={lead} />
              </p>
            </div>

            <div className="flex flex-wrap gap-2 text-xs">
              <label className="flex items-center gap-1.5 cursor-pointer text-ink/60">
                <input
                  type="checkbox"
                  checked={lead.bounced}
                  onChange={(e) => patch({ bounced: e.target.checked })}
                  className="accent-mpower-orange"
                />
                Bounced
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer text-ink/60">
                <input
                  type="checkbox"
                  checked={lead.unsubscribed}
                  onChange={(e) => patch({ unsubscribed: e.target.checked })}
                  className="accent-mpower-orange"
                />
                Unsubscribed
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer text-ink/60">
                <input
                  type="checkbox"
                  checked={lead.not_interested}
                  onChange={(e) => patch({ not_interested: e.target.checked })}
                  className="accent-mpower-orange"
                />
                Not interested
              </label>
            </div>

            <div>
              <p className="text-xs font-mono uppercase tracking-wider text-ink/40 mb-2">
                Audit timeline
              </p>
              <ul className="space-y-1.5 text-xs text-ink/60 max-h-48 overflow-y-auto">
                {lead.events.map((ev) => (
                  <li key={ev.id} className="flex gap-2">
                    <span className="text-ink/35">
                      {ev.created_at ? ev.created_at.replace("T", " ").slice(0, 16) : ""}
                    </span>
                    <span>
                      <span className="font-medium text-ink/75">{ev.kind}</span>
                      {ev.from_value || ev.to_value
                        ? ` ${ev.from_value ?? ""}→${ev.to_value ?? ""}`
                        : ""}
                      {ev.actor_name ? ` · ${ev.actor_name}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
