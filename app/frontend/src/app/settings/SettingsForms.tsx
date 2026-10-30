"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, Field, OkText, PrimaryButton } from "@/components/Shared/ui";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm">
      <h2 className="font-heading text-base font-semibold text-ink mb-4">
        {title}
      </h2>
      {children}
    </section>
  );
}

export default function SettingsForms({
  initialFirst,
  initialLast,
}: {
  initialFirst: string;
  initialLast: string;
}) {
  const router = useRouter();
  const [first, setFirst] = useState(initialFirst);
  const [last, setLast] = useState(initialLast);
  const [nameMsg, setNameMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [savingName, setSavingName] = useState(false);

  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [savingPw, setSavingPw] = useState(false);

  const saveName = async (e: React.FormEvent) => {
    e.preventDefault();
    if (savingName) return;
    setNameMsg(null);
    setSavingName(true);
    try {
      const res = await apiFetch("/api/auth/me/name", {
        method: "PATCH",
        body: JSON.stringify({ first_name: first, last_name: last }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new ApiError(res.status, body.detail ?? "Could not save your name.");
      }
      setNameMsg({ ok: true, text: "Name updated." });
      router.refresh();
    } catch (err) {
      setNameMsg({
        ok: false,
        text: err instanceof ApiError ? err.message : "Could not save your name.",
      });
    } finally {
      setSavingName(false);
    }
  };

  const savePw = async (e: React.FormEvent) => {
    e.preventDefault();
    if (savingPw) return;
    setPwMsg(null);
    setSavingPw(true);
    try {
      const res = await apiFetch("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: cur, new_password: next }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new ApiError(res.status, body.detail ?? "Could not change password.");
      }
      setPwMsg({ ok: true, text: "Password changed." });
      setCur("");
      setNext("");
    } catch (err) {
      setPwMsg({
        ok: false,
        text: err instanceof ApiError ? err.message : "Could not change password.",
      });
    } finally {
      setSavingPw(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card title="Display name">
        <form onSubmit={saveName} className="space-y-4">
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
          {nameMsg &&
            (nameMsg.ok ? (
              <OkText>{nameMsg.text}</OkText>
            ) : (
              <ErrorText>{nameMsg.text}</ErrorText>
            ))}
          <PrimaryButton type="submit" disabled={savingName || !first || !last}>
            {savingName ? "Saving…" : "Save name"}
          </PrimaryButton>
        </form>
      </Card>

      <Card title="Change password">
        <form onSubmit={savePw} className="space-y-4">
          <Field
            type="password"
            value={cur}
            onChange={(e) => setCur(e.target.value)}
            placeholder="Current password"
            autoComplete="current-password"
            required
          />
          <Field
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            placeholder="New password (8+ characters)"
            autoComplete="new-password"
            minLength={8}
            required
          />
          {pwMsg &&
            (pwMsg.ok ? (
              <OkText>{pwMsg.text}</OkText>
            ) : (
              <ErrorText>{pwMsg.text}</ErrorText>
            ))}
          <PrimaryButton type="submit" disabled={savingPw || !cur || next.length < 8}>
            {savingPw ? "Updating…" : "Update password"}
          </PrimaryButton>
        </form>
      </Card>
    </div>
  );
}
