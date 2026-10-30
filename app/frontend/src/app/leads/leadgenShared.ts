// Shared types + tiny helpers for the Generate-Leads wizard and the read-only
// Lists tab. Both read from the same /api/leadgen/lists contract, so the shapes
// live here once.

export type LeadgenCustomer = {
  id: number;
  name: string;
  type: string | null; // OEM | Reseller | Distributor | null
  country: string;
  category: string;
  website: string | null;
  band: string | null;
};

export type RoleGroup = {
  group: string;
  titles: string[];
};

export type LeadgenLists = {
  categories: string[];
  categories_grouped: { product: string[]; service: string[] };
  types: string[];
  countries: string[];
  customers: LeadgenCustomer[];
  roles: RoleGroup[];
};

// Job snapshot (mirrors backend JobOut) for the 6-stage Generate progress modal.
export type LeadgenJob = {
  id: number;
  kind: string;
  status: "pending" | "running" | "done" | "error" | "paused";
  total: number;
  processed: number;
  created_count: number;
  skipped_count: number;
  error_count: number;
  credits_used: number;
  message: string | null;
  detail: string | null; // JSON string {stage,current,customer_index,customer_total}
};

// Band pill colours, matching the Customers tab.
export const BAND_BADGE: Record<string, { label: string; cls: string }> = {
  Sure: { label: "SalesPath Sure", cls: "bg-ok-green/15 text-ok-green" },
  Likely: { label: "SalesPath Likely", cls: "bg-mpower-orange/15 text-mpower-orange" },
  Unsure: { label: "SalesPath Unsure", cls: "bg-warn-amber/15 text-warn-amber" },
  No: { label: "SalesPath No", cls: "bg-err-red/15 text-err-red" },
};
