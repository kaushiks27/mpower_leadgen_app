"use client";

import { useEffect, useState } from "react";

// Client-side session/role exposure. Mirrors lib/session.ts (server-only) for
// nav role-gating. Fail-safe: only release `loading` on a clean 200 or a
// definitive 401 — transient errors keep gates restrictive.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export type Role = "admin" | "rep" | null;

export type ClientSession = {
  signedIn: boolean;
  userId: number | null;
  email: string | null;
  role: Role;
  firstName: string | null;
  lastName: string | null;
  loading: boolean;
};

const INITIAL: ClientSession = {
  signedIn: false,
  userId: null,
  email: null,
  role: null,
  firstName: null,
  lastName: null,
  loading: true,
};

export function isAdminRole(role: Role): boolean {
  return role === "admin";
}

export function useSession(): ClientSession {
  const [state, setState] = useState<ClientSession>(INITIAL);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/auth/me`, { credentials: "include", cache: "no-store" })
      .then(async (res) => {
        if (cancelled) return;
        if (res.status === 401) {
          setState({ ...INITIAL, loading: false });
          return;
        }
        if (!res.ok) return; // transient — stay restrictive
        const data = await res.json();
        setState({
          signedIn: !!data.signed_in,
          userId: data.id ?? null,
          email: data.email ?? null,
          role: (data.role ?? null) as Role,
          firstName: data.first_name ?? null,
          lastName: data.last_name ?? null,
          loading: false,
        });
      })
      .catch(() => {
        /* keep loading=true on network error */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
