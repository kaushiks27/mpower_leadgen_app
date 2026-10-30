"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import UserMenu from "@/components/Shared/UserMenu";
import { useSession } from "@/lib/auth";

const BRAND = process.env.NEXT_PUBLIC_BRAND_NAME ?? "SalesPath by BuLoop AI";

type NavLink = { href: string; label: string; adminOnly?: boolean };

// Shell nav. Dashboard + Leads + Pipeline for everyone; Campaigns + Users for
// admins.
const NAV_LINKS: NavLink[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/leads", label: "Leads" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/campaigns", label: "Campaigns", adminOnly: true },
  { href: "/mpower-brain", label: "mPower's Brain", adminOnly: true },
  { href: "/admin/users", label: "Users", adminOnly: true },
];

export default function AppNavbar() {
  const pathname = usePathname();
  const { role } = useSession();
  const isAdmin = role === "admin";

  const links = NAV_LINKS.filter((l) => !l.adminOnly || isAdmin);

  return (
    <nav className="sticky top-0 z-30 bg-canvas/85 backdrop-blur-xl border-b border-ink/10 px-6 py-3">
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
        <Link href="/dashboard" className="flex items-center gap-2">
          <div className="w-8 h-8 bg-mpower-orange rounded-lg flex items-center justify-center">
            <span className="font-heading font-bold text-white text-xs">
              {(BRAND[0] ?? "M").toUpperCase()}
            </span>
          </div>
          <span className="font-heading font-bold text-ink text-base tracking-tight">
            {BRAND}
          </span>
        </Link>
        <div className="flex items-center gap-1">
          {links.map(({ href, label }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={
                  "px-4 py-2 rounded-xl text-sm font-body font-medium btn-press " +
                  (active
                    ? "bg-mpower-orange/10 text-mpower-orange"
                    : "text-ink/60 hover:text-ink hover:bg-ink/5")
                }
              >
                {label}
              </Link>
            );
          })}
          <UserMenu />
        </div>
      </div>
    </nav>
  );
}
