"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText } from "@/components/Shared/ui";
import { FlagBadges } from "../leads/LeadsListClient";
import {
  STAGE_LABEL,
  STAGES,
  formatINR,
  type BoardResponse,
  type CampaignOption,
  type Lead,
  type Stage,
} from "../leads/types";

export default function PipelineBoard() {
  const [columns, setColumns] = useState<Record<Stage, Lead[]> | null>(null);
  const [ownerOptions, setOwnerOptions] = useState<string[]>([]);
  const [campaignOptions, setCampaignOptions] = useState<CampaignOption[]>([]);
  const [ownerFilter, setOwnerFilter] = useState<string[]>([]);
  const [campaignFilter, setCampaignFilter] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [dragId, setDragId] = useState<number | null>(null);
  const [overStage, setOverStage] = useState<Stage | null>(null);

  const load = useCallback(async () => {
    setErr("");
    try {
      const params = new URLSearchParams();
      ownerFilter.forEach((o) => params.append("owner", o));
      campaignFilter.forEach((c) => params.append("campaign_id", String(c)));
      const qs = params.toString();
      const res = await apiFetch(`/api/leads/board${qs ? `?${qs}` : ""}`, {
        method: "GET",
      });
      if (!res.ok) throw new ApiError(res.status, "Could not load board.");
      const data = (await res.json()) as BoardResponse;
      setColumns(data.columns);
      // Option lists are unfiltered (they describe the whole board), so only
      // refresh them when nothing is selected — keeps the menus stable.
      if (ownerFilter.length === 0 && campaignFilter.length === 0) {
        setOwnerOptions(data.owner_options ?? []);
        setCampaignOptions(data.campaign_options ?? []);
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load board.");
    } finally {
      setLoading(false);
    }
  }, [ownerFilter, campaignFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleOwner = (o: string) =>
    setOwnerFilter((prev) =>
      prev.includes(o) ? prev.filter((x) => x !== o) : [...prev, o],
    );
  const toggleCampaign = (id: number) =>
    setCampaignFilter((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  const clearFilters = () => {
    setOwnerFilter([]);
    setCampaignFilter([]);
  };
  const hasFilters = ownerFilter.length > 0 || campaignFilter.length > 0;

  const drop = async (stage: Stage) => {
    const id = dragId;
    setOverStage(null);
    setDragId(null);
    if (id === null) return;
    // Find current stage; no-op if dropped in the same column.
    const current = columns
      ? (Object.keys(columns) as Stage[]).find((s) =>
          columns[s].some((l) => l.id === id),
        )
      : undefined;
    if (current === stage) return;
    try {
      const res = await apiFetch(`/api/leads/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ stage }),
      });
      if (!res.ok) throw new ApiError(res.status, "Move failed.");
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Move failed.");
    }
  };

  const filterBar = (
    <div className="space-y-3 mb-5">
      {ownerOptions.length > 0 && (
        <FilterRow label="Owner">
          {ownerOptions.map((o) => (
            <Chip key={o} on={ownerFilter.includes(o)} onClick={() => toggleOwner(o)}>
              {o}
            </Chip>
          ))}
        </FilterRow>
      )}
      {campaignOptions.length > 0 && (
        <FilterRow label="Campaign">
          {campaignOptions.map((c) => (
            <Chip
              key={c.id}
              on={campaignFilter.includes(c.id)}
              onClick={() => toggleCampaign(c.id)}
            >
              {c.name}
            </Chip>
          ))}
        </FilterRow>
      )}
      {hasFilters && (
        <button
          type="button"
          onClick={clearFilters}
          className="text-xs font-body text-ink/55 hover:text-mpower-orange btn-press"
        >
          Clear filters
        </button>
      )}
    </div>
  );

  if (loading) return <p className="text-sm text-ink/50">Loading…</p>;
  if (err) return <ErrorText>{err}</ErrorText>;
  if (!columns) return null;

  return (
    <div>
      {filterBar}
      <div className="overflow-x-auto pb-4">
      <div className="flex gap-4 min-w-max">
        {STAGES.map((stage) => {
          const leads = columns[stage] ?? [];
          const isOver = overStage === stage;
          return (
            <div
              key={stage}
              onDragOver={(e) => {
                e.preventDefault();
                if (overStage !== stage) setOverStage(stage);
              }}
              onDragLeave={() => {
                if (overStage === stage) setOverStage(null);
              }}
              onDrop={() => void drop(stage)}
              className={
                "w-64 shrink-0 rounded-2xl border p-3 transition-colors " +
                (isOver
                  ? "border-mpower-orange bg-mpower-orange/5"
                  : "border-ink/10 bg-canvas/50")
              }
            >
              <div className="flex items-center justify-between mb-3 px-1">
                <span className="text-xs font-mono uppercase tracking-wider text-ink/50">
                  {STAGE_LABEL[stage]}
                </span>
                <span className="text-xs text-ink/35">{leads.length}</span>
              </div>
              <div className="space-y-2 min-h-[60px]">
                {leads.map((l) => (
                  <div
                    key={l.id}
                    draggable
                    onDragStart={() => setDragId(l.id)}
                    onDragEnd={() => {
                      setDragId(null);
                      setOverStage(null);
                    }}
                    className={
                      "bg-surface border border-ink/10 rounded-xl p-3 shadow-sm cursor-grab active:cursor-grabbing btn-press " +
                      (dragId === l.id ? "opacity-50" : "hover:border-mpower-orange/40")
                    }
                  >
                    <p className="font-body text-sm font-medium text-ink truncate">
                      {l.full_name}
                    </p>
                    <p className="text-xs text-ink/50 truncate">
                      {[l.title, l.company_name].filter(Boolean).join(" · ") || "—"}
                    </p>
                    <div className="mt-1.5 flex items-center justify-between gap-2">
                      <FlagBadges lead={l} />
                      {l.value_inr != null && (
                        <span className="text-xs font-semibold text-mpower-orange tabular-nums whitespace-nowrap">
                          {formatINR(l.value_inr)}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      </div>
    </div>
  );
}

function FilterRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-mono uppercase tracking-wider text-ink/40 w-20 shrink-0">
        {label}
      </span>
      {children}
    </div>
  );
}

function Chip({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={
        "px-3 py-1 rounded-lg text-xs font-body btn-press border " +
        (on
          ? "bg-mpower-orange/10 text-mpower-orange border-mpower-orange/40"
          : "text-ink/65 border-ink/15 hover:bg-ink/5")
      }
    >
      {on ? "✓ " : ""}
      {children}
    </button>
  );
}
