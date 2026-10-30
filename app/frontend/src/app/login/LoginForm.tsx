"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, Field, PrimaryButton } from "@/components/Shared/ui";

export default function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setError("");
    setSubmitting(true);
    try {
      const res = await apiFetch("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        throw new ApiError(
          res.status,
          res.status === 401
            ? "Wrong email or password."
            : "Something went wrong. Please try again.",
        );
      }
      router.replace("/dashboard");
      router.refresh();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Something went wrong.",
      );
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <Field
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@company.com"
        autoComplete="email"
        autoFocus
        required
      />
      <Field
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        autoComplete="current-password"
        required
      />
      {error && <ErrorText>{error}</ErrorText>}
      <PrimaryButton type="submit" disabled={submitting || !email || !password}>
        {submitting ? "Signing in…" : "Sign in"}
      </PrimaryButton>
      <div className="text-center pt-1">
        <Link
          href="/forgot-password"
          className="text-xs font-body text-ink/50 hover:text-mpower-orange btn-press"
        >
          Forgot your password?
        </Link>
      </div>
    </form>
  );
}
