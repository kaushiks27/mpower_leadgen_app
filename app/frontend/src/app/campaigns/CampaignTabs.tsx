"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Sub-tabs under the Campaigns area: the campaign blueprints (list) and the live
// Monitor (S-9 — placeholder for now). Active tab is highlighted by pathname.
const TABS = [
  { href: "/campaigns", label: "Campaigns" },
  { href: "/campaigns/monitor", label: "Monitor" },
];

export default function CampaignTabs() {
  const pathname = usePathname();
  return (
    <div className="flex gap-1 mb-6 border-b border-ink/10">
      {TABS.map(({ href, label }) => {
        const active =
          href === "/campaigns"
            ? pathname === "/campaigns"
            : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={
              "px-4 py-2 -mb-px text-sm font-body font-medium border-b-2 btn-press " +
              (active
                ? "border-mpower-orange text-mpower-orange"
                : "border-transparent text-ink/55 hover:text-ink")
            }
          >
            {label}
          </Link>
        );
      })}
    </div>
  );
}
