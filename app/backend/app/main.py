"""FastAPI entry point — registers routers + fail-fast env checks + admin seed.

Registration-only edits live here per OP #11; feature logic stays in modules.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

from app.admin_users import router as admin_users_router
from app.auth import router as auth_router
from app.auth.seed import seed_admin_if_missing
from app.brain import router as brain_router
from app.brain.seed import seed_brain_catalog_if_empty
from app.campaigns import router as campaigns_router
from app.competitors import router as competitors_router
from app.competitors.seed import seed_competitors_if_empty
from app.config import router as config_router
from app.customers import router as customers_router
from app.customers.seed import seed_customers_if_empty
from app.config.seed import seed_catalog_if_missing
from app.cost import router as cost_router
from app.dashboard import router as dashboard_router
from app.db import init_db
from app.email import set_key_resolver
from app.email_gen import router as email_gen_router
from app.enrichment import router as enrichment_router
from app.instantly import router as instantly_router
from app.jobs import router as jobs_router
from app.leadgen import router as leadgen_router
from app.leads import router as leads_router
from app.leads.seed import seed_sample_leads_if_missing
from app.scraping import router as scraping_router
from app.settings import router as settings_router
from app.settings.keys import load_cache, resolve_api_key
from app.suppression import router as suppression_router

# SECRET_KEY required for future signed surfaces; fail fast if absent.
REQUIRED_ENV_VARS = ("SECRET_KEY",)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            f"missing required env vars: {', '.join(missing)} — refusing to start"
        )
    await init_db()
    await seed_admin_if_missing()
    await seed_catalog_if_missing()
    # Brain catalog: re-seed mPower's verified products/services from a bundled
    # snapshot when empty (ephemeral SQLite resets on redeploy) — no AI credits.
    await seed_brain_catalog_if_empty()
    # Competitors: re-load a classified competitor snapshot when empty (ephemeral
    # SQLite resets on redeploy) — no AI credits. No-op until a snapshot exists.
    await seed_competitors_if_empty()
    await seed_customers_if_empty()
    # Sample leads for visual-verify (S-4). Off by default; real leads come from
    # the scrapers at S-5/S-6. Gated so prod isn't polluted with samples.
    if os.environ.get("SEED_SAMPLE_LEADS", "").strip().lower() in {"1", "true", "yes"}:
        await seed_sample_leads_if_missing()
    # 08062026_cr CR-6: best-effort backfill of the structured lead taxonomy
    # (category / customer_type / country / customer_item_id) for leads created
    # before CR-6. Idempotent + non-destructive — a no-op once attributed.
    from app.db import async_session
    from app.leadgen.backfill import backfill_lead_taxonomy

    async with async_session() as _bf_db:
        filled = await backfill_lead_taxonomy(_bf_db)
        if filled:
            logger.warning("[backfill] CR-6 lead taxonomy filled on %d lead(s)", filled)
    # Load encrypted API keys into the in-process cache, then point the email
    # sender at the DB-wins/env-fallback resolver for the Resend key.
    await load_cache()
    set_key_resolver(lambda: resolve_api_key("resend"))
    email_on = (
        os.environ.get("EMAIL_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    )
    if email_on:
        sender = os.environ.get("EMAIL_FROM", "<missing EMAIL_FROM>")
        logger.warning("[email] EMAIL_ENABLED=true · sender=%s", sender)
    else:
        logger.warning(
            "[email] EMAIL_ENABLED=false · transactional emails are logged-only "
            "(no Resend call). Set EMAIL_ENABLED=true to deliver."
        )
    yield


app = FastAPI(title="SalesPath by BuLoop AI", version="0.1.0", lifespan=lifespan)

# CORS allow-list. Canonical dev = localhost:3030. Set CORS_EXTRA_ORIGINS
# (comma-separated) for other ports/hosts.
_CORS_DEFAULTS = ["http://localhost:3030", "http://127.0.0.1:3030"]
_cors_extra = [
    o.strip() for o in os.environ.get("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_DEFAULTS + _cors_extra,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_users_router)
app.include_router(brain_router)
app.include_router(competitors_router)
app.include_router(customers_router)
app.include_router(config_router)
app.include_router(cost_router)
app.include_router(settings_router)
app.include_router(campaigns_router)
app.include_router(scraping_router)
app.include_router(jobs_router)
app.include_router(enrichment_router)
app.include_router(email_gen_router)
app.include_router(instantly_router)
app.include_router(suppression_router)
app.include_router(leads_router)
app.include_router(leadgen_router)
app.include_router(dashboard_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
