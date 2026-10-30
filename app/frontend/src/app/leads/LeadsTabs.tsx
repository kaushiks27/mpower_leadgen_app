"use client";

import { useState } from "react";

import LeadsListClient from "./LeadsListClient";
import SuppressionClient from "./SuppressionClient";

type Tab = "leads" | "suppression";

export default function LeadsTabs() {
  const [tab, setTab] = useState<Tab>("leads");
  const tabs: { key: Tab; label: string }[] = [
    { key: "leads", label: "Leads" },
    { key: "suppression", label: "Suppression" },
  ];

  return (
    <div>
      <div className="flex items-center gap-1 border-b border-ink/10 mb-8">
        {tabs.map(({ key, label }) => {
          const active = tab === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={
                "px-4 py-2.5 -mb-px text-sm font-body font-medium btn-press border-b-2 " +
                (active
                  ? "border-mpower-orange text-mpower-orange"
                  : "border-transparent text-ink/55 hover:text-ink")
              }
            >
              {label}
            </button>
          );
        })}
      </div>

      {tab === "leads" && <LeadsListClient />}
      {tab === "suppression" && <SuppressionClient />}
    </div>
  );
}
