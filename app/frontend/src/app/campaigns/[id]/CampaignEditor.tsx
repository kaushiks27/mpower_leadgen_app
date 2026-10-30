"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import CampaignForm from "../CampaignForm";
import CampaignLeads from "./CampaignLeads";
import InstantlyPush from "./InstantlyPush";
import LeadMixPanel from "./LeadMixPanel";

// 08062026_cr CR-2/3/5 — the campaign detail page. The scrape-era action bar
// (Generate / Enrich / Icebreaker) is GONE; campaigns now pull prepared leads
// from the master list. Layout: read-only Lead mix + Add Leads → editable form
// (name / owner / icebreaker toggle / send window / sequence) → Instantly → the
// campaign's lead list. A lead pull or save bumps the refresh key so every panel
// re-reads (lead-mix, Instantly gate, lead list).
export default function CampaignEditor({ campaignId }: { campaignId: number }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const [requireIcebreaker, setRequireIcebreaker] = useState(true);

  const loadToggle = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/campaigns/${campaignId}`, { method: "GET" });
      if (res.ok) {
        const c = (await res.json()) as { require_icebreaker: boolean };
        setRequireIcebreaker(c.require_icebreaker);
      }
    } catch {
      /* default stays true */
    }
  }, [campaignId]);

  useEffect(() => {
    void loadToggle();
  }, [loadToggle, refreshKey]);

  const bump = () => setRefreshKey((k) => k + 1);

  return (
    <div className="space-y-6">
      <LeadMixPanel
        campaignId={campaignId}
        requireIcebreaker={requireIcebreaker}
        refreshKey={refreshKey}
        onChanged={bump}
      />
      <CampaignForm campaignId={campaignId} onSaved={bump} />
      <div className="pt-6 border-t border-ink/10 space-y-6">
        <InstantlyPush
          campaignId={campaignId}
          reloadKey={refreshKey}
          onJobComplete={bump}
        />
        <CampaignLeads campaignId={campaignId} refreshKey={refreshKey} />
      </div>
    </div>
  );
}
