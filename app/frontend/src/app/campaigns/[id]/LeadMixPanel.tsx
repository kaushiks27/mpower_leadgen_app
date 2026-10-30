"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, PrimaryButton } from "@/components/Shared/ui";
import type { LeadMix } from "../types";
import AddLeadsModal from "./AddLeadsModal";

// 08062026_cr CR-3/5 — read-only "lead mix" for a campaign: the distinct
// categories / customer types / countries its leads span, plus the derived send
// timezone (majority country). An "Add Leads from List" button opens the picker.
export default function LeadMixPanel({
  campaignId,
  requireIcebreaker,
  refreshKey,
  onChanged,
}: {
  campaignId: number;
  requireIcebreaker: boolean;
  refreshKey: number;
  onChanged: () => void;
}) {
  const [mix, setMix] = useState<LeadMix | null>(null);
  const [err, setErr] = useState("");
  const [picking, setPicking] = useState(false);

  const load = useCallback(async () => {
    setErr("");
    try {
      const res = await apiFetch(`/api/campaigns/${campaignId}/lead-mix`, {
        method: "GET",
      });
      if (!res.ok) throw new ApiError(res.status, "Could not load lead mix.");
      setMix((await res.json()) as LeadMix);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load lead mix.");
    }
  }, [campaignId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const Chips = ({ values }: { values: string[] }) =>
    values.length === 0 ? (
      <span className="text-sm text-ink/40">—</span>
    ) : (
      <span className="flex flex-wrap gap-1.5">
        {values.map((v) => (
          <span
            key={v}
            className="px-2 py-0.5 rounded-full text-xs font-body bg-ink/[0.06] text-ink/70"
          >
            {v}
          </span>
        ))}
      </span>
    );

  return (
    <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-heading text-base font-semibold text-ink">
          Lead mix
          {mix ? (
            <span className="ml-2 text-xs font-body text-ink/40">
              {mix.lead_count} lead{mix.lead_count === 1 ? "" : "s"}
            </span>
          ) : null}
        </h2>
        <PrimaryButton
          type="button"
          onClick={() => setPicking(true)}
          className="w-auto px-4 text-sm"
        >
          Add Leads from List
        </PrimaryButton>
      </div>

      {err ? (
        <ErrorText>{err}</ErrorText>
      ) : !mix ? (
        <p className="text-sm text-ink/50">Loading…</p>
      ) : (
        <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <Row label="Categories"><Chips values={mix.categories} /></Row>
          <Row label="ICP type"><Chips values={mix.customer_types} /></Row>
          <Row label="Countries"><Chips values={mix.countries} /></Row>
          <Row label="Send timezone">
            <span className="font-body text-ink/80">{mix.timezone}</span>
            <span className="text-xs text-ink/40 ml-2">(auto from majority country)</span>
          </Row>
        </div>
      )}

      {picking && (
        <AddLeadsModal
          campaignId={campaignId}
          requireIcebreaker={requireIcebreaker}
          onClose={() => setPicking(false)}
          onAdded={() => {
            void load();
            onChanged();
          }}
        />
      )}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-mono uppercase tracking-wider text-ink/40 mb-1">{label}</p>
      <div>{children}</div>
    </div>
  );
}
