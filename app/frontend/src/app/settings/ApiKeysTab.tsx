"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, Field, OkText, PrimaryButton } from "@/components/Shared/ui";

type KeyStatus = {
  provider: string;
  is_set: boolean;
  last4: string | null;
  source: string; // db | env | none
};

const PROVIDERS: { provider: string; label: string; hint: string }[] = [
  { provider: "apify", label: "Apify", hint: "Scrapes companies + employees" },
  { provider: "apollo", label: "Apollo", hint: "Finds emails + phones" },
  { provider: "instantly", label: "Instantly", hint: "Sends cold-email campaigns" },
  { provider: "resend", label: "Resend", hint: "Sends app + alert emails" },
  {
    provider: "millionverifier",
    label: "MillionVerifier",
    hint: "Verifies emails are deliverable",
  },
  {
    provider: "anthropic",
    label: "Anthropic (Claude)",
    hint: "Writes the one-line icebreakers",
  },
];

function SourceBadge({ source }: { source: string }) {
  if (source === "db")
    return (
      <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-ok-green/15 text-ok-green">
        SAVED
      </span>
    );
  if (source === "env")
    return (
      <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-warn-amber/15 text-warn-amber">
        FROM ENV
      </span>
    );
  return (
    <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-ink/10 text-ink/50">
      NOT SET
    </span>
  );
}

function ProviderCard({
  provider,
  label,
  hint,
  status,
  reload,
}: {
  provider: string;
  label: string;
  hint: string;
  status: KeyStatus | undefined;
  reload: () => Promise<void>;
}) {
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy || !val.trim()) return;
    setMsg(null);
    setBusy(true);
    try {
      const res = await apiFetch(`/api/settings/keys/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ api_key: val }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new ApiError(res.status, b.detail ?? "Could not save key.");
      }
      setVal("");
      setMsg({ ok: true, text: "Saved." });
      await reload();
    } catch (e2) {
      setMsg({ ok: false, text: e2 instanceof ApiError ? e2.message : "Could not save key." });
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    if (busy) return;
    if (!confirm(`Clear the saved ${label} key? It will fall back to the env value if set.`)) return;
    setMsg(null);
    setBusy(true);
    try {
      const res = await apiFetch(`/api/settings/keys/${provider}`, { method: "DELETE" });
      if (!res.ok) throw new ApiError(res.status, "Could not clear key.");
      setMsg({ ok: true, text: "Cleared." });
      await reload();
    } catch (e2) {
      setMsg({ ok: false, text: e2 instanceof ApiError ? e2.message : "Could not clear key." });
    } finally {
      setBusy(false);
    }
  };

  const masked = status?.last4 ? `••••••••${status.last4}` : "—";

  return (
    <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-heading text-base font-semibold text-ink">{label}</h2>
            <SourceBadge source={status?.source ?? "none"} />
          </div>
          <p className="text-xs text-ink/45 mt-0.5">{hint}</p>
        </div>
        <span className="font-mono text-sm text-ink/60">{masked}</span>
      </div>

      <form onSubmit={save} className="flex flex-col sm:flex-row gap-2">
        <Field
          type="password"
          value={val}
          onChange={(e) => setVal(e.target.value)}
          placeholder={status?.is_set ? "Paste a new key to rotate" : "Paste API key"}
          autoComplete="off"
          className="sm:flex-1"
        />
        <PrimaryButton type="submit" disabled={busy || !val.trim()} className="sm:w-32">
          {busy ? "Saving…" : status?.is_set ? "Rotate" : "Save"}
        </PrimaryButton>
      </form>

      <div className="flex items-center justify-between mt-3">
        {msg ? (
          msg.ok ? (
            <OkText>{msg.text}</OkText>
          ) : (
            <ErrorText>{msg.text}</ErrorText>
          )
        ) : (
          <span />
        )}
        {status?.source === "db" && (
          <button
            type="button"
            onClick={clear}
            disabled={busy}
            className="text-xs font-body text-err-red hover:underline btn-press disabled:opacity-50"
          >
            clear saved key
          </button>
        )}
      </div>
    </section>
  );
}

export default function ApiKeysTab() {
  const [statuses, setStatuses] = useState<KeyStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [listErr, setListErr] = useState("");

  const load = useCallback(async () => {
    setListErr("");
    try {
      const res = await apiFetch("/api/settings/keys", { method: "GET" });
      if (!res.ok) throw new ApiError(res.status, "Could not load keys.");
      setStatuses((await res.json()) as KeyStatus[]);
    } catch (e) {
      setListErr(e instanceof ApiError ? e.message : "Could not load keys.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p className="text-sm text-ink/50">Loading…</p>;
  if (listErr) return <ErrorText>{listErr}</ErrorText>;

  const byProvider = (p: string) => statuses.find((s) => s.provider === p);

  return (
    <div className="space-y-6">
      <p className="text-sm text-ink/55 -mt-2">
        Keys are encrypted before they are saved. We only ever show the last 4
        characters back to you.
      </p>
      {PROVIDERS.map((p) => (
        <ProviderCard key={p.provider} {...p} status={byProvider(p.provider)} reload={load} />
      ))}
    </div>
  );
}
