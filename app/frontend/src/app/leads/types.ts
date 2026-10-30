// Shared types + labels for the lead engine (S-4). Stages mirror the backend
// PIPELINE_STAGES tuple (server is SSOT; /api/leads/meta is the live source).

export type Stage =
  | "new"
  | "enriched"
  | "queued"
  | "emailed"
  | "replied"
  | "interested"
  | "won";

export const STAGES: Stage[] = [
  "new",
  "enriched",
  "queued",
  "emailed",
  "replied",
  "interested",
  "won",
];

export const STAGE_LABEL: Record<Stage, string> = {
  new: "New",
  enriched: "Enriched",
  queued: "Queued",
  emailed: "Emailed",
  replied: "Replied",
  interested: "Interested",
  won: "Won",
};

export type Lead = {
  id: number;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string | null;
  email_status: string | null; // S-6 MV verdict: valid|risky|invalid|unknown|no_email
  phone: string | null;
  linkedin_url: string | null;
  icebreaker: string | null;
  title: string | null;
  location: string | null; // CR-6: company country (structured)
  category: string | null; // CR-6: product/service category from the customer
  customer_type: string | null; // CR-6: OEM | Reseller | Distributor
  customer_item_id: number | null;
  company_id: number | null;
  company_name: string | null;
  campaign_id: number | null;
  campaign_name: string | null;
  campaign_owner: string | null; // S-7 free-text owner of the lead's campaign
  value_inr: number | null; // S-7 potential deal value, whole INR (exact int)
  stage: Stage;
  bounced: boolean;
  unsubscribed: boolean;
  not_interested: boolean;
  suppressed: boolean;
  source: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
};

// S-6 email-verification badge. Send-eligible (S-8) = "valid" + "catch_all"
// (both on the company's own domain); every other state is excluded from push.
export const EMAIL_STATUS_BADGE: Record<
  string,
  { label: string; cls: string }
> = {
  // SalesPath quality brand: Sure (verified) + Likely (on-domain catch-all) are
  // send-eligible; No (email on a different company's domain) is not.
  valid: { label: "SalesPath Sure", cls: "bg-ok-green/15 text-ok-green" },
  catch_all: { label: "SalesPath Likely", cls: "bg-mpower-orange/15 text-mpower-orange" },
  off_domain: { label: "SalesPath No", cls: "bg-err-red/15 text-err-red" },
  risky: { label: "Risky", cls: "bg-mpower-orange/15 text-mpower-orange" }, // legacy rows
  invalid: { label: "Invalid", cls: "bg-err-red/15 text-err-red" },
  unknown: { label: "Unknown", cls: "bg-ink/10 text-ink/60" },
  no_email: { label: "No email", cls: "bg-ink/10 text-ink/50" },
};

export function emailStatusBadge(status: string | null) {
  if (!status) return null;
  return EMAIL_STATUS_BADGE[status] ?? { label: status, cls: "bg-ink/10 text-ink/60" };
}

export type LeadEvent = {
  id: number;
  kind: string;
  from_value: string | null;
  to_value: string | null;
  actor_name: string | null;
  created_at: string;
};

export type LeadDetail = Lead & { events: LeadEvent[] };

export type CampaignOption = { id: number; name: string };

export type BoardResponse = {
  stages: Stage[];
  columns: Record<Stage, Lead[]>;
  owner_options: string[];
  campaign_options: CampaignOption[];
};

// S-7 — format whole INR in the Indian grouping system (e.g. 250000 -> ₹2,50,000).
export function formatINR(value: number | null): string {
  if (value === null || value === undefined) return "—";
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `₹${value}`;
  }
}

export type SuppressionRow = {
  id: number;
  kind: "email" | "linkedin_url";
  value: string;
  reason: string | null;
  active: boolean;
  created_by_name: string | null;
  created_at: string;
};
