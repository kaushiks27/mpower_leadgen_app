"use client";

import Link from "next/link";
import { useState } from "react";

import { apiFetch } from "@/lib/api";
import { Field, OkText, PrimaryButton } from "@/components/Shared/ui";

export default function ForgotForm() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      // Always succeeds visibly (no account enumeration).
      await apiFetch("/api/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
    } finally {
      setSent(true);
      setSubmitting(false);
    }
  };

  if (sent) {
    return (
      <div className="space-y-4">
        <OkText>
          If that email is on file, a reset link is on its way. Check your inbox.
        </OkText>
        <Link
          href="/login"
          className="block text-center text-xs font-body text-ink/50 hover:text-mpower-orange btn-press"
        >
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <Field
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@company.com"
        autoComplete="email"
        autoFocus
        required
      />
      <PrimaryButton type="submit" disabled={submitting || !email}>
        {submitting ? "Sending…" : "Send reset link"}
      </PrimaryButton>
      <Link
        href="/login"
        className="block text-center text-xs font-body text-ink/50 hover:text-mpower-orange btn-press"
      >
        Back to sign in
      </Link>
    </form>
  );
}
