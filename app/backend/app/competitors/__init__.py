"""mPower's Brain — Competitors intelligence module.

Second Brain surface (after Products & Services): a worldwide, exhaustively-
discovered list of mPower's **direct competitors** — other drone-battery / pack
manufacturers — split into Global and Local (India) views. Each competitor is
classified by Claude into a SalesPath band measuring *is-this-a-true-competitor*
confidence, tagged with the mPower product/service category it competes in, and
enriched with the customers it is "selling to" (best-effort from its own site +
public trade records; blank + note when none can be found).

Self-contained (OP #11): imports only infrastructure (db, jobs, settings.keys,
auth). It READS the Products & Services categories from `brain_catalog_items` as
a data dependency (a SQL read of the table, never a code import of the brain
module) so the competitor Category column stays exactly in sync with mPower's own
catalog categories. Owns its own thin Apify (search + crawl) + Claude clients.
"""

from app.competitors.router import router

__all__ = ["router"]
