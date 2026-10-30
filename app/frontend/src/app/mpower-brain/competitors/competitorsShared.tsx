"use client";

export type Competitor = {
  id: number;
  name: string;
  website: string | null;
  website_verified: boolean | null;
  domain: string | null;
  country: string | null;
  scope: "local" | "global";
  category: string | null;
  selling_to: string | null;
  selling_to_note: string | null;
  band: string | null;
  band_reason: string | null;
  band_confidence: string | null;
  locked_fields: string[];
  manual: boolean;
  archived: boolean;
  source_url: string | null;
};

// SalesPath true-competitor band pill (same scale as Products & Services).
// Here the band means: how confident Claude is this is a real DIRECT competitor
// (a drone-battery / pack manufacturer) — not a drone OEM, cell-only supplier,
// or reseller. Manual rows are always Sure (human-authoritative).
export const BAND_BADGE: Record<string, { label: string; cls: string }> = {
  Sure: { label: "SalesPath Sure", cls: "bg-ok-green/15 text-ok-green" },
  Likely: { label: "SalesPath Likely", cls: "bg-mpower-orange/15 text-mpower-orange" },
  Unsure: { label: "SalesPath Unsure", cls: "bg-warn-amber/15 text-warn-amber" },
  No: { label: "SalesPath No", cls: "bg-err-red/15 text-err-red" },
};

export const BAND_RANK: Record<string, number> = { Sure: 0, Likely: 1, Unsure: 2, No: 3 };

export function BandPill({ c }: { c: Competitor }) {
  if (!c.band) return <span className="text-ink/35 text-xs">not classified</span>;
  const b = BAND_BADGE[c.band] ?? { label: c.band, cls: "bg-ink/10 text-ink/60" };
  const conf = c.band_confidence
    ? ` · ${Math.round(Number(c.band_confidence) * 100)}%`
    : "";
  return (
    <span
      className={"px-2 py-0.5 rounded-full text-xs font-body font-medium whitespace-nowrap " + b.cls}
      title={(c.band_reason ?? "") + (c.band_confidence ? `\nConfidence: ${c.band_confidence}` : "")}
    >
      {b.label}
      {conf}
    </span>
  );
}
