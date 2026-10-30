"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

type DevInfo = {
  apify_actor: string;
  apify_input: string;
  products_url: string;
  service_slugs: string[];
  claude_model: string;
  claude_system: string;
  claude_user_template: string;
};

// Greyed-out, collapsible, READ-ONLY dev reference: shows the exact Apify
// sourcing strategy + Claude verifier prompt that "Sync" runs. Pulled from the
// backend so it never drifts from the real code. For dev visibility only.
export default function DevReference() {
  const [info, setInfo] = useState<DevInfo | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch("/api/brain/catalog/dev-info", { method: "GET" });
        if (res.ok) setInfo((await res.json()) as DevInfo);
      } catch {
        /* read-only reference; ignore */
      }
    })();
  }, []);

  if (!info) return null;

  const apifyText =
    `Actor: ${info.apify_actor}\n` +
    `Crawl input:\n${info.apify_input}\n\n` +
    `Structured products: GET ${info.products_url}\n\n` +
    `Service pages (slugs):\n  - ${info.service_slugs.join("\n  - ")}`;

  const claudeText =
    `Model: ${info.claude_model}\n\n` +
    `===== SYSTEM (rubric + good/bad examples) =====\n${info.claude_system}\n\n` +
    `===== USER (per row) =====\n${info.claude_user_template}`;

  return (
    <div className="mt-2 space-y-2 opacity-70">
      <p className="text-xs font-mono uppercase tracking-wider text-ink/35">
        Dev reference (read-only)
      </p>
      <DevBlock title="Apify sourcing strategy (what “Sync” crawls + pulls)" text={apifyText} />
      <DevBlock title="Claude verifier prompt (line-by-line data-confidence)" text={claudeText} />
    </div>
  );
}

function DevBlock({ title, text }: { title: string; text: string }) {
  return (
    <details className="rounded-xl border border-ink/10 bg-ink/[0.03]">
      <summary className="cursor-pointer select-none px-4 py-2.5 text-sm font-body text-ink/55 hover:text-ink/75">
        {title}
      </summary>
      <pre className="px-4 py-3 text-xs font-mono text-ink/55 whitespace-pre-wrap break-words border-t border-ink/10 max-h-80 overflow-auto">
        {text}
      </pre>
    </details>
  );
}
