"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Sub-tabs under mPower's Brain. Products & Services + Competitors + Customers are live.
const ACTIVE_TABS = [
  { href: "/mpower-brain", label: "Products & Services" },
  { href: "/mpower-brain/competitors", label: "Competitors" },
  { href: "/mpower-brain/customers", label: "Customers" },
  { href: "/mpower-brain/lists", label: "Lists" },
];
const SOON_TABS: string[] = [];

export default function MpowerBrainTabs() {
  const pathname = usePathname();
  return (
    <div className="flex items-center gap-1 mb-6 border-b border-ink/10">
      {ACTIVE_TABS.map(({ href, label }) => {
        const active = pathname === href;
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
      {SOON_TABS.map((label) => (
        <span
          key={label}
          className="px-4 py-2 -mb-px text-sm font-body font-medium border-b-2 border-transparent text-ink/30 cursor-not-allowed select-none"
          title="Coming soon"
        >
          {label}
          <span className="ml-1.5 text-[10px] uppercase tracking-wide text-ink/25">
            soon
          </span>
        </span>
      ))}
    </div>
  );
}
