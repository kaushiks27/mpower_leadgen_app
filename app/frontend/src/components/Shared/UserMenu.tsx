"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth";

function initials(first: string | null, last: string | null, email: string | null) {
  const f = (first ?? "").trim();
  const l = (last ?? "").trim();
  if (f && l) return (f[0] + l[0]).toUpperCase();
  if (email) return email[0]!.toUpperCase();
  return "U";
}

export default function UserMenu() {
  const router = useRouter();
  const { email, role, firstName, lastName } = useSession();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const isAdmin = role === "admin";

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const logout = async () => {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } finally {
      setOpen(false);
      router.replace("/login");
      router.refresh();
    }
  };

  return (
    <div className="relative ml-2 pl-3 border-l border-ink/10" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-9 h-9 rounded-full bg-ink text-white text-xs font-heading font-semibold flex items-center justify-center hover:bg-ink/90 btn-press"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Open account menu"
      >
        {initials(firstName, lastName, email)}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-60 bg-surface border border-ink/10 rounded-xl shadow-lg py-1 z-40"
        >
          <div className="px-4 pt-3 pb-3 border-b border-ink/10">
            <p className="text-[10px] font-mono tracking-wider text-ink/40">
              SIGNED IN
            </p>
            {email && (
              <p className="text-sm font-body text-ink truncate">{email}</p>
            )}
            {role && (
              <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[10px] font-mono bg-mpower-orange/10 text-mpower-orange capitalize">
                {role}
              </span>
            )}
          </div>

          <Link
            href="/settings"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="block px-4 py-2 text-sm font-body text-ink hover:bg-ink/5 btn-press"
          >
            Account settings
          </Link>

          {isAdmin && (
            <Link
              href="/admin/users"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="block px-4 py-2 text-sm font-body text-ink hover:bg-ink/5 btn-press"
            >
              Users
            </Link>
          )}

          <div className="border-t border-ink/10 mt-1 pt-1">
            <button
              type="button"
              role="menuitem"
              onClick={logout}
              disabled={signingOut}
              className="w-full text-left px-4 py-2 text-sm font-body text-ink hover:bg-ink/5 disabled:opacity-50 btn-press"
            >
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
