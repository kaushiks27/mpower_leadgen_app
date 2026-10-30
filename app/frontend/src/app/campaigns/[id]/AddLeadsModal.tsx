"use client";

import { useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, PrimaryButton } from "@/components/Shared/ui";
import LeadPickerList from "../LeadPickerList";

// 08062026_cr CR-2 — the detail-page "Add Leads from List" modal. Pulls the
// selected eligible+unassigned master leads into THIS campaign, then the parent
// refreshes the lead list + lead-mix + Instantly gate.
export default function AddLeadsModal({
  campaignId,
  requireIcebreaker,
  onClose,
  onAdded,
}: {
  campaignId: number;
  requireIcebreaker: boolean;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const add = async () => {
    if (selected.size === 0 || saving) return;
    setSaving(true);
    setErr("");
    try {
      const res = await apiFetch(`/api/campaigns/${campaignId}/add-leads`, {
        method: "POST",
        body: JSON.stringify({ lead_ids: Array.from(selected) }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new ApiError(res.status, body.detail ?? "Could not add leads.");
      }
      onAdded();
      onClose();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not add leads.");
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 bg-ink/40 overflow-y-auto">
      <div className="bg-surface rounded-2xl shadow-xl border border-ink/10 w-full max-w-2xl my-8 flex flex-col max-h-[88vh]">
        <div className="flex items-start justify-between gap-3 p-6 pb-4 border-b border-ink/10">
          <div>
            <h3 className="font-heading text-lg font-semibold text-ink">Add leads from list</h3>
            <p className="text-xs font-body text-ink/50 mt-0.5">
              Only unassigned, verified leads
              {requireIcebreaker ? " with an icebreaker" : ""} can be pulled in.
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

        <div className="flex-1 overflow-y-auto p-6">
          <LeadPickerList
            requireIcebreaker={requireIcebreaker}
            selected={selected}
            onToggle={toggle}
            onSelectAllShown={(ids) =>
              setSelected((prev) => {
                const next = new Set(prev);
                ids.forEach((i) => next.add(i));
                return next;
              })
            }
            onClear={() => setSelected(new Set())}
          />
          {err && (
            <div className="mt-3">
              <ErrorText>{err}</ErrorText>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 p-6 pt-4 border-t border-ink/10">
          <p className="text-xs text-ink/45">
            {selected.size} lead{selected.size === 1 ? "" : "s"} selected.
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 rounded-xl border border-ink/15 font-body text-ink/70 hover:bg-canvas btn-press"
            >
              Cancel
            </button>
            <PrimaryButton
              type="button"
              onClick={add}
              disabled={saving || selected.size === 0}
              className="w-auto px-6"
            >
              {saving ? "Adding…" : `Add ${selected.size || ""} lead${selected.size === 1 ? "" : "s"}`}
            </PrimaryButton>
          </div>
        </div>
      </div>
    </div>
  );
}
