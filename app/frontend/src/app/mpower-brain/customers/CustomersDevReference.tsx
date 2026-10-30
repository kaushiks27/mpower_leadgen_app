"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

type DevInfo = {
  search_actor: string;
  crawl_actor: string;
  sources: string[];
  type_sources: string[];
  sample_queries: string[];
  enrichment_queries: string[];
  mpower_categories: string[];
  pipeline_steps: string[];
  claude_model: string;
  claude_system: string;
  claude_user_template: string;
  extract_model: string;
  extract_system: string;
  extract_user_template: string;
};

// Greyed-out, collapsible, READ-ONLY dev reference: the exact discovery sources +
// sample queries + Claude classifier prompt that "Sync Customers" runs. Pulled from
// the backend so it never drifts from the real code.
export default function CustomersDevReference() {
  const [info, setInfo] = useState<DevInfo | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch("/api/brain/customers/dev-info", { method: "GET" });
        if (res.ok) setInfo((await res.json()) as DevInfo);
      } catch {
        /* read-only reference; ignore */
      }
    })();
  }, []);

  if (!info) return null;

  const discoveryText =
    `Search actor: ${info.search_actor}\n` +
    `Crawl actor:  ${info.crawl_actor}\n\n` +
    `Discovery sources (two lanes — drone OEMs + resellers/distributors — per mPower category):\n  - ${info.sources.join("\n  - ")}\n\n` +
    `Type signal sources (OEM vs Reseller vs Distributor):\n  - ${info.type_sources.join("\n  - ")}\n\n` +
    `mPower categories customers are analysed against (live from Products & Services):\n  - ${info.mpower_categories.join("\n  - ") || "(none yet — sync the catalog first)"}\n\n` +
    `Sample round-1 discovery queries:\n  - ${info.sample_queries.join("\n  - ")}\n\n` +
    `Per-customer enrichment pass (line-by-line, run before the classifier — fills location/category/type, survives cookie/JS walls):\n  - ${info.enrichment_queries.join("\n  - ")}`;

  const pipelineText =
    `The category-first pipeline "Sync Customers" runs, top to bottom:\n\n  ${info.pipeline_steps.join("\n  ")}\n\n` +
    `Category is set from the originating category-search (the search that found the company); ` +
    `Claude only fills it when discovery left it blank, never reassigns. ` +
    `Location + type come from the one site crawl, extracted by the cheap model, then ` +
    `the strong model grades the genuine-customer band LAST over the fully-enriched line ` +
    `(a battery manufacturer is banded "No" — it is a competitor, not a customer).`;

  const extractText =
    `Model: ${info.extract_model} (cheap — terse field extraction, OP#10)\n\n` +
    `===== SYSTEM (extract location / type / name — NO band) =====\n${info.extract_system}\n\n` +
    `===== USER (per customer) =====\n${info.extract_user_template}`;

  const claudeText =
    `Model: ${info.claude_model} (strong — the load-bearing band)\n\n` +
    `===== SYSTEM (genuine-customer rubric + good/bad examples) =====\n${info.claude_system}\n\n` +
    `===== USER (per customer) =====\n${info.claude_user_template}`;

  return (
    <div className="mt-2 space-y-2 opacity-70">
      <p className="text-xs font-mono uppercase tracking-wider text-ink/35">
        Dev reference (read-only)
      </p>
      <DevBlock title="Pipeline (the 5 steps “Sync” runs, in order)" text={pipelineText} />
      <DevBlock title="Discovery strategy (sources + sample queries “Sync” runs)" text={discoveryText} />
      <DevBlock title="Extract pass prompt (cheap model — location / type)" text={extractText} />
      <DevBlock title="Classifier prompt (strong model — genuine-customer band)" text={claudeText} />
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
