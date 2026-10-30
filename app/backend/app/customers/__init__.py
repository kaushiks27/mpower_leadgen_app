"""mPower's Brain — Customers intelligence module.

Third Brain surface (after Products & Services + Competitors): a worldwide,
category-first list of mPower's prospective **customers** — companies mPower would
SELL drone batteries TO — in two types:
  * OEM        — a drone MANUFACTURER (builds drones, buys packs). NOT a battery maker.
  * Reseller / Distributor — of drone batteries / mPower's product categories.

Split into Global and Local (India) views. Each customer is classified by Claude into
a genuine-customer band (Sure/Likely/Unsure/No) and a Type (OEM/Reseller/Distributor);
a company that manufactures batteries itself is banded "No" (it is a competitor).

Self-contained (OP #11): imports only infrastructure (db, jobs, settings.keys, auth).
READS the Products & Services categories from `brain_catalog_items` as a data dependency
(a SQL read, never a code import) so the Category column stays in sync with mPower's own
catalog. Owns its own thin Apify (search + crawl) + Claude clients."""

from app.customers.router import router

__all__ = ["router"]
