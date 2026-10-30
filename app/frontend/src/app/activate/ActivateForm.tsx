"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, Field, OkText, PrimaryButton } from "@/components/Shared/ui";

export default function ActivateForm({ token }: { token: string }) {
  const router = useRouter();
  const [pw, setPw] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting || !token) return;
    setError("");
    setSubmitting(true);
    try {
      const res = await apiFetch("/api/admin/users/activate", {
        method: "POST",
        body: JSON.stringify({ token, new_password: pw }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new ApiError(res.status, body.detail ?? "This link has expired or is invalid.");
      }
      setDone(true);
      setTimeout(() => router.replace("/login"), 1500);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "This link has expired or is invalid.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!token) {
    return <ErrorText>This activation link is missing its token.</ErrorText>;
  }
  if (done) {
    return <OkText>Password set! Redirecting you to sign in…</OkText>;
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <Field
        type="password"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
        placeholder="Choose a password (8+ characters)"
        autoComplete="new-password"
        minLength={8}
        required
        autoFocus
      />
      {error && <ErrorText>{error}</ErrorText>}
      <PrimaryButton type="submit" disabled={submitting || pw.length < 8}>
        {submitting ? "Setting…" : "Set password"}
      </PrimaryButton>
      <Link
        href="/login"
        className="block text-center text-xs font-body text-ink/50 hover:text-mpower-orange btn-press"
      >
        Already activated? Sign in
      </Link>
    </form>
  );
}
