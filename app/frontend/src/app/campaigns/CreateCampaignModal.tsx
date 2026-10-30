"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, Field, PrimaryButton } from "@/components/Shared/ui";
import LeadPickerList from "./LeadPickerList";
import type { Campaign } from "./types";

// 08062026_cr CR-3/4/5 — the in-app create-campaign modal. Collects only the
// name + the require-icebreaker toggle + the leads to pull. Everything else
// (taxonomy, timezone) is derived; the email sequence is built on the detail
// page. On create we navigate to the new campaign's detail page.
export default function CreateCampaignModal({
  onClose,
}: {
  onClose: () => void;
}) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [requireIcebreaker, setRequireIcebreaker] = useState(true);
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

  const create = async () => {
    if (!name.trim()) {
      setErr("Give the campaign a name.");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      const res = await apiFetch("/api/campaigns", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          require_icebreaker: requireIcebreaker,
          lead_ids: Array.from(selected),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new ApiError(res.status, body.detail ?? "Could not create campaign.");
      }
      const created = body as Campaign;
      router.push(`/campaigns/${created.id}`);
      router.refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not create campaign.");
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 bg-ink/40 overflow-y-auto">
      <div className="bg-surface rounded-2xl shadow-xl border border-ink/10 w-full max-w-2xl my-8 flex flex-col max-h-[88vh]">
        <div className="flex items-start justify-between gap-3 p-6 pb-4 border-b border-ink/10">
          <div>
            <h3 className="font-heading text-lg font-semibold text-ink">New campaign</h3>
            <p className="text-xs font-body text-ink/50 mt-0.5">
              Name it, choose whether an icebreaker is required, and pull leads from
              your master list. Add the email sequence on the next screen.
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

        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          <div>
            <label className="block text-sm font-body font-medium text-ink mb-1.5">
              Campaign name
            </label>
            <Field
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Drone OEMs — India Q3"
            />
          </div>

          <label className="flex items-center gap-2.5 cursor-pointer text-sm font-body text-ink/80">
            <input
              type="checkbox"
              checked={requireIcebreaker}
              onChange={(e) => setRequireIcebreaker(e.target.checked)}
              className="accent-mpower-orange"
            />
            Require an icebreaker before a lead can be added or sent
          </label>

          <div>
            <p className="text-sm font-body font-medium text-ink mb-2">Pull leads</p>
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
          </div>

          {err && <ErrorText>{err}</ErrorText>}
        </div>

        <div className="flex items-center justify-between gap-3 p-6 pt-4 border-t border-ink/10">
          <p className="text-xs text-ink/45">
            {selected.size} lead{selected.size === 1 ? "" : "s"} will be added.
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
              onClick={create}
              disabled={saving || !name.trim()}
              className="w-auto px-6"
            >
              {saving ? "Creating…" : "Create campaign"}
            </PrimaryButton>
          </div>
        </div>
      </div>
    </div>
  );
}
