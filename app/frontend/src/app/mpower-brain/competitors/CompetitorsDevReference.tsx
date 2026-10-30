"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

type DevInfo = {
  search_actor: string;
  crawl_actor: string;
  sources: string[];
  selling_to_sources: string[];
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
// sample queries + Claude classifier prompt that "Sync Competitors" runs. Pulled
// from the backend so it never drifts from the real code.
export default function CompetitorsDevReference() {
  const [info, setInfo] = useState<DevInfo | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch("/api/brain/competitors/dev-info", { method: "GET" });
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
    `Discovery sources (queries designed per source + per mPower category):\n  - ${info.sources.join("\n  - ")}\n\n` +
    `"Selling-to" enrichment sources (best-effort; blank + note when empty):\n  - ${info.selling_to_sources.join("\n  - ")}\n\n` +
    `mPower categories competitors are analysed against (live from Products & Services):\n  - ${info.mpower_categories.join("\n  - ") || "(none yet — sync the catalog first)"}\n\n` +
    `Sample round-1 discovery queries:\n  - ${info.sample_queries.join("\n  - ")}\n\n` +
    `Per-competitor enrichment pass (line-by-line, run before the classifier — fills country/category/selling-to, survives cookie/JS walls):\n  - ${info.enrichment_queries.join("\n  - ")}`;

  const pipelineText =
    `The category-first pipeline "Sync Competitors" runs, top to bottom:\n\n  ${info.pipeline_steps.join("\n  ")}\n\n` +
    `Category is set from the originating category-search (the search that found the company); ` +
    `Claude only fills it when discovery left it blank, never reassigns. ` +
    `Country + selling-to come from the one site crawl, extracted by the cheap model, then ` +
    `the strong model grades the band LAST over the fully-enriched line.`;

  const extractText =
    `Model: ${info.extract_model} (cheap — terse field extraction, OP#10)\n\n` +
    `===== SYSTEM (extract country / selling-to / name — NO band) =====\n${info.extract_system}\n\n` +
    `===== USER (per competitor) =====\n${info.extract_user_template}`;

  const claudeText =
    `Model: ${info.claude_model} (strong — the load-bearing band)\n\n` +
    `===== SYSTEM (true-competitor rubric + good/bad examples) =====\n${info.claude_system}\n\n` +
    `===== USER (per competitor) =====\n${info.claude_user_template}`;

  return (
    <div className="mt-2 space-y-2 opacity-70">
      <p className="text-xs font-mono uppercase tracking-wider text-ink/35">
        Dev reference (read-only)
      </p>
      <DevBlock title="Pipeline (the 5 steps “Sync” runs, in order)" text={pipelineText} />
      <DevBlock title="Discovery strategy (sources + sample queries “Sync” runs)" text={discoveryText} />
      <DevBlock title="Extract pass prompt (cheap model — country / selling-to)" text={extractText} />
      <DevBlock title="Classifier prompt (strong model — true-competitor band)" text={claudeText} />
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
