"use client";

import { useState } from "react";

import ApiKeysTab from "./ApiKeysTab";
import CatalogTab from "./CatalogTab";
import CostTab from "./CostTab";
import CreditCeilingsTab from "./CreditCeilingsTab";
import SettingsForms from "./SettingsForms";

type Tab = "account" | "catalog" | "keys" | "budget" | "cost";

export default function SettingsTabs({
  isAdmin,
  initialFirst,
  initialLast,
}: {
  isAdmin: boolean;
  initialFirst: string;
  initialLast: string;
}) {
  const [tab, setTab] = useState<Tab>("account");

  const tabs: { key: Tab; label: string }[] = [
    { key: "account", label: "Account" },
    ...(isAdmin
      ? ([
          { key: "catalog", label: "Catalog" },
          { key: "keys", label: "API keys" },
          { key: "budget", label: "Budget" },
          { key: "cost", label: "Cost" },
        ] as { key: Tab; label: string }[])
      : []),
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

      {tab === "account" && (
        <SettingsForms initialFirst={initialFirst} initialLast={initialLast} />
      )}
      {tab === "catalog" && isAdmin && <CatalogTab />}
      {tab === "keys" && isAdmin && <ApiKeysTab />}
      {tab === "budget" && isAdmin && <CreditCeilingsTab />}
      {tab === "cost" && isAdmin && <CostTab />}
    </div>
  );
}
