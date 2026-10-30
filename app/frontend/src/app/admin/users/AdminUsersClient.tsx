"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, Field, OkText, PrimaryButton } from "@/components/Shared/ui";

type Row = {
  id: number;
  email: string;
  first_name: string | null;
  last_name: string | null;
  role: string;
  pending: boolean;
  created_at: string;
};

export default function AdminUsersClient() {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [listErr, setListErr] = useState("");

  // invite form
  const [email, setEmail] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [role, setRole] = useState("rep");
  const [inviteMsg, setInviteMsg] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const [inviting, setInviting] = useState(false);

  const load = useCallback(async () => {
    setListErr("");
    try {
      const res = await apiFetch("/api/admin/users", { method: "GET" });
      if (!res.ok) throw new ApiError(res.status, "Could not load users.");
      setRows((await res.json()) as Row[]);
    } catch (err) {
      setListErr(err instanceof ApiError ? err.message : "Could not load users.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const invite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (inviting) return;
    setInviteMsg(null);
    setInviting(true);
    try {
      const res = await apiFetch("/api/admin/users/invite", {
        method: "POST",
        body: JSON.stringify({
          email,
          first_name: first,
          last_name: last,
          role,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new ApiError(res.status, body.detail ?? "Could not send invite.");
      }
      if (body.email_failed) {
        setInviteMsg({
          ok: false,
          text: `${body.fallback_message} ${body.fallback_url}`,
        });
      } else {
        setInviteMsg({ ok: true, text: `Invite emailed to ${email}.` });
      }
      setEmail("");
      setFirst("");
      setLast("");
      setRole("rep");
      await load();
    } catch (err) {
      setInviteMsg({
        ok: false,
        text: err instanceof ApiError ? err.message : "Could not send invite.",
      });
    } finally {
      setInviting(false);
    }
  };

  const changeRole = async (id: number, newRole: string) => {
    await apiFetch(`/api/admin/users/${id}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role: newRole }),
    });
    await load();
  };

  const remove = async (id: number, email: string) => {
    if (!confirm(`Remove ${email}? This cannot be undone.`)) return;
    await apiFetch(`/api/admin/users/${id}`, { method: "DELETE" });
    await load();
  };

  const resend = async (id: number) => {
    await apiFetch(`/api/admin/users/${id}/resend`, { method: "POST" });
    setInviteMsg({ ok: true, text: "Invite resent." });
  };

  return (
    <div className="space-y-8">
      <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm">
        <h2 className="font-heading text-base font-semibold text-ink mb-4">
          Invite a teammate
        </h2>
        <form onSubmit={invite} className="space-y-4">
          <Field
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="teammate@company.com"
            required
          />
          <div className="grid grid-cols-2 gap-3">
            <Field
              value={first}
              onChange={(e) => setFirst(e.target.value)}
              placeholder="First name"
              required
            />
            <Field
              value={last}
              onChange={(e) => setLast(e.target.value)}
              placeholder="Last name"
              required
            />
          </div>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-full px-4 py-3 rounded-xl border border-ink/15 font-body text-ink bg-surface focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 focus:border-mpower-orange btn-press"
          >
            <option value="rep">Sales rep</option>
            <option value="admin">Admin</option>
          </select>
          {inviteMsg &&
            (inviteMsg.ok ? (
              <OkText>{inviteMsg.text}</OkText>
            ) : (
              <ErrorText>{inviteMsg.text}</ErrorText>
            ))}
          <PrimaryButton
            type="submit"
            disabled={inviting || !email || !first || !last}
          >
            {inviting ? "Sending…" : "Send invite"}
          </PrimaryButton>
        </form>
      </section>

      <section className="bg-surface border border-ink/10 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-ink/10">
          <h2 className="font-heading text-base font-semibold text-ink">
            Team ({rows.length})
          </h2>
        </div>
        {loading ? (
          <p className="px-6 py-6 text-sm text-ink/50">Loading…</p>
        ) : listErr ? (
          <p className="px-6 py-6">
            <ErrorText>{listErr}</ErrorText>
          </p>
        ) : (
          <ul className="divide-y divide-ink/10">
            {rows.map((u) => (
              <li
                key={u.id}
                className="px-6 py-4 flex items-center justify-between gap-4"
              >
                <div className="min-w-0">
                  <p className="text-sm font-body text-ink truncate">
                    {u.first_name || u.last_name
                      ? `${u.first_name ?? ""} ${u.last_name ?? ""}`.trim()
                      : u.email}
                  </p>
                  <p className="text-xs text-ink/45 truncate">{u.email}</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {u.pending && (
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-warn-amber/15 text-warn-amber">
                      PENDING
                    </span>
                  )}
                  <select
                    value={u.role}
                    onChange={(e) => changeRole(u.id, e.target.value)}
                    className="text-xs font-body border border-ink/15 rounded-lg px-2 py-1 bg-surface focus:outline-none focus:ring-1 focus:ring-mpower-orange/40"
                  >
                    <option value="rep">rep</option>
                    <option value="admin">admin</option>
                  </select>
                  {u.pending && (
                    <button
                      type="button"
                      onClick={() => resend(u.id)}
                      className="text-xs font-body text-mpower-orange hover:underline btn-press"
                    >
                      resend
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => remove(u.id, u.email)}
                    className="text-xs font-body text-err-red hover:underline btn-press"
                  >
                    remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
