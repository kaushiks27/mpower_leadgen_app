"use client";

export type CatalogItem = {
  id: number;
  kind: "product" | "service";
  name: string;
  category: string | null;
  price_inr: string | null;
  price_locked: boolean;
  band: string | null;
  band_reason: string | null;
  band_confidence: string | null;
  manual: boolean;
  archived: boolean;
  source_url: string | null;
};

// SalesPath data-confidence pill. Manual rows are always Sure (human-authoritative).
export const BAND_BADGE: Record<string, { label: string; cls: string }> = {
  Sure: { label: "SalesPath Sure", cls: "bg-ok-green/15 text-ok-green" },
  Likely: { label: "SalesPath Likely", cls: "bg-mpower-orange/15 text-mpower-orange" },
  Unsure: { label: "SalesPath Unsure", cls: "bg-warn-amber/15 text-warn-amber" },
  No: { label: "SalesPath No", cls: "bg-err-red/15 text-err-red" },
};

// Sort rank for the band column (best → worst).
export const BAND_RANK: Record<string, number> = { Sure: 0, Likely: 1, Unsure: 2, No: 3 };

export function BandPill({ item }: { item: CatalogItem }) {
  if (!item.band) return <span className="text-ink/35 text-xs">not verified</span>;
  const b = BAND_BADGE[item.band] ?? { label: item.band, cls: "bg-ink/10 text-ink/60" };
  const conf = item.band_confidence
    ? ` · ${Math.round(Number(item.band_confidence) * 100)}%`
    : "";
  return (
    <span
      className={"px-2 py-0.5 rounded-full text-xs font-body font-medium whitespace-nowrap " + b.cls}
      title={(item.band_reason ?? "") + (item.band_confidence ? `\nConfidence: ${item.band_confidence}` : "")}
    >
      {b.label}
      {conf}
    </span>
  );
}

export function formatPrice(s: string | null): string {
  if (s === null || s === "") return "—";
  const n = Number(s);
  if (Number.isNaN(n)) return `₹${s}`;
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}
