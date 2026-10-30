"use client";

export type Customer = {
  id: number;
  name: string;
  website: string | null;
  website_verified: boolean | null;
  domain: string | null;
  country: string | null;
  phone: string | null;
  email: string | null;
  email_quality: string | null; // valid | catch_all | invalid | unknown | null
  discovery_source: string | null; // google | maps | linkedin | indiamart | …
  scope: "local" | "global";
  category: string | null;
  ctype: string | null; // OEM | Reseller | Distributor | null
  band: string | null;
  band_reason: string | null;
  band_confidence: string | null;
  locked_fields: string[];
  manual: boolean;
  archived: boolean;
  source_url: string | null;
};

export const CTYPES = ["OEM", "Reseller", "Distributor"] as const;

// Type pill — OEM (drone maker) vs the reseller/distributor channel.
export const CTYPE_BADGE: Record<string, { label: string; cls: string }> = {
  OEM: { label: "OEM", cls: "bg-mpower-orange/15 text-mpower-orange" },
  Reseller: { label: "Reseller", cls: "bg-ok-green/15 text-ok-green" },
  Distributor: { label: "Distributor", cls: "bg-ok-green/15 text-ok-green" },
};

export function CtypePill({ c }: { c: Customer }) {
  if (!c.ctype) return <span className="text-ink/35 text-xs">—</span>;
  const t = CTYPE_BADGE[c.ctype] ?? { label: c.ctype, cls: "bg-ink/10 text-ink/60" };
  return (
    <span className={"px-2 py-0.5 rounded-full text-xs font-body font-medium whitespace-nowrap " + t.cls}>
      {t.label}
    </span>
  );
}

// Genuine-customer band pill. Here the band means: how confident Claude is this is a
// real prospective CUSTOMER (a drone OEM, or a bona-fide reseller/distributor) — a
// battery manufacturer is "No" (a competitor). Manual rows are always Sure.
export const BAND_BADGE: Record<string, { label: string; cls: string }> = {
  Sure: { label: "SalesPath Sure", cls: "bg-ok-green/15 text-ok-green" },
  Likely: { label: "SalesPath Likely", cls: "bg-mpower-orange/15 text-mpower-orange" },
  Unsure: { label: "SalesPath Unsure", cls: "bg-warn-amber/15 text-warn-amber" },
  No: { label: "SalesPath No", cls: "bg-err-red/15 text-err-red" },
};

export const BAND_RANK: Record<string, number> = { Sure: 0, Likely: 1, Unsure: 2, No: 3 };

export function BandPill({ c }: { c: Customer }) {
  if (!c.band) return <span className="text-ink/35 text-xs">not classified</span>;
  const b = BAND_BADGE[c.band] ?? { label: c.band, cls: "bg-ink/10 text-ink/60" };
  const conf = c.band_confidence ? ` · ${Math.round(Number(c.band_confidence) * 100)}%` : "";
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
