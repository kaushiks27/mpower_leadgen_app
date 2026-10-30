import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

// Server-side session resolution for App-Router pages. Forwards the mp_session
// cookie to FastAPI /api/auth/me. BACKEND_URL is the in-container address.
const API_BASE =
  process.env.BACKEND_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8030";

const SESSION_COOKIE = "mp_session";

export type SessionUser = {
  id: number | null;
  email: string | null;
  role: string | null;
  firstName: string | null;
  lastName: string | null;
};

export type Session = { signedIn: boolean; user: SessionUser | null };

export async function getSession(): Promise<Session> {
  const token = cookies().get(SESSION_COOKIE)?.value;
  if (!token) return { signedIn: false, user: null };
  try {
    const res = await fetch(`${API_BASE}/api/auth/me`, {
      method: "GET",
      headers: { cookie: `${SESSION_COOKIE}=${token}` },
      cache: "no-store",
    });
    if (!res.ok) return { signedIn: false, user: null };
    const data = await res.json();
    return {
      signedIn: !!data.signed_in,
      user: data.id
        ? {
            id: data.id,
            email: data.email ?? null,
            role: data.role ?? null,
            firstName: data.first_name ?? null,
            lastName: data.last_name ?? null,
          }
        : null,
    };
  } catch {
    return { signedIn: false, user: null };
  }
}

export async function requireSession(): Promise<Session> {
  const sess = await getSession();
  if (!sess.signedIn) redirect("/login");
  return sess;
}

export async function requireAdmin(): Promise<Session> {
  const sess = await requireSession();
  if (sess.user?.role !== "admin") redirect("/dashboard");
  return sess;
}

export async function redirectIfSignedIn(target = "/dashboard"): Promise<void> {
  const { signedIn } = await getSession();
  if (signedIn) redirect(target);
}

export function initialsFromUser(user: SessionUser | null): string {
  if (!user) return "U";
  const f = (user.firstName ?? "").trim();
  const l = (user.lastName ?? "").trim();
  if (f && l) return (f[0] + l[0]).toUpperCase();
  if (user.email) return user.email[0]!.toUpperCase();
  return "U";
}
