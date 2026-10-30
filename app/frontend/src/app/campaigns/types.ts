// Shared types + constants for the Campaigns feature (S-3).

export type CatalogItem = { id: number; name: string };

export type Step = {
  id?: number;
  step_order?: number;
  wait_days: number;
  subject: string;
  body: string;
};

export type LeadMix = {
  categories: string[];
  customer_types: string[];
  countries: string[];
  timezone: string;
  lead_count: number;
};

export type Campaign = {
  id: number;
  name: string;
  owner: string | null; // S-7 free-text campaign owner
  require_icebreaker: boolean; // CR-2 per-campaign toggle
  category_id: number;
  target_category_id: number;
  geography_id: number;
  category_name: string | null;
  target_category_name: string | null;
  geography_name: string | null;
  role_ids: number[];
  icp_filter_ids: number[];
  role_names: string[];
  icp_filter_names: string[];
  timezone: string;
  target_lead_count: number;
  send_days: string[];
  send_start_hour: number;
  send_end_hour: number;
  status: string;
  archived: boolean;
  step_count: number;
  created_at: string;
  updated_at: string;
  steps?: Step[];
};

// Insertable placeholders (values fill in later sending slices). {icebreaker} is
// the per-lead AI line generated in S-7 — usually placed at the top of the body.
export const PLACEHOLDERS = [
  "{icebreaker}",
  "{first_name}",
  "{company}",
  "{role}",
  "{sender_name}",
  "{sender_company}",
] as const;

export const SEND_DAYS = [
  { key: "mon", label: "Mon" },
  { key: "tue", label: "Tue" },
  { key: "wed", label: "Wed" },
  { key: "thu", label: "Thu" },
  { key: "fri", label: "Fri" },
  { key: "sat", label: "Sat" },
  { key: "sun", label: "Sun" },
] as const;

export const DEFAULT_TZ = "Asia/Kolkata";

// Full IANA list in modern browsers; fall back to a small list otherwise.
export function timezoneOptions(): string[] {
  try {
    const fn = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] })
      .supportedValuesOf;
    if (fn) return fn("timeZone");
  } catch {
    /* fall through */
  }
  return [DEFAULT_TZ, "UTC", "America/New_York", "Europe/London", "Asia/Singapore"];
}
