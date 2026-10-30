# mPower Lead-Gen

A sales lead-generation and pipeline app: find companies, find and verify the
right people, write first lines, and push campaigns to Instantly.

- **Backend:** FastAPI + SQLAlchemy (async) + SQLite, in `app/backend/`
- **Frontend:** Next.js (App Router) + TypeScript + Tailwind, in `app/frontend/`
- **Deploy:** one Docker image (Caddy + supervisord) on Fly.io: `Dockerfile`, `fly.toml`

This repository contains code only. No customer, prospect, or competitor data
is included, and none should be committed (see "Data rules" below).

## Run it locally

Needs Python 3.13 and Node 20.

```bash
# Backend: http://localhost:8030
cd app/backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env           # then edit the values
set -a; source .env; set +a
.venv/bin/python -m uvicorn app.main:app --reload --port 8030

# Frontend: http://localhost:3030 (in a second terminal)
cd app/frontend
npm install
cp .env.example .env.local
npm run dev
```

Log in with the `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` you set. The admin
account is created on first boot when the database is empty.

Set `SEED_SAMPLE_LEADS=true` to load a few fictional sample leads.

## API keys

Third-party keys (Apify, Apollo, Instantly, MillionVerifier, Anthropic, Resend)
can be entered on the **Settings** page, where they are stored encrypted, or
set as environment variables (`APIFY_API_KEY`, `APOLLO_API_KEY`, and so on).
Use your own development or test accounts. Never commit a key.

## Tests

```bash
cd app/backend && .venv/bin/python -m pytest tests/ -q   # backend
cd app/frontend && npm run typecheck                     # frontend types
```

Run both before every pull request.

## Project rules

These come from how the app is used in production. Please keep them.

1. **Money is exact.** Deal values, prices, forecasts, and costs use
   `decimal.Decimal`, never floats.
2. **Leads are never hard-deleted.** Archive (soft delete) only, so nothing is
   silently lost.
3. **Changes are traceable.** Changes to a deal's stage, owner, or value record
   who made them and when.
4. **AI output is a draft, never a decision.** Claude may write email copy and
   suggestions, but it must not set stored numbers or move a deal between stages.
5. **One folder per feature.** Each feature lives in its own folder under
   `app/backend/app/<feature>/` (models, router, logic) with a matching folder
   under `app/frontend/src/app/<feature>/`. Features import shared
   infrastructure (`db/`, `auth/`). Shared code does not import features.

## Data rules

- Do not commit `.env` files, databases (`*.db`, `*.sqlite`), exports
  (`.csv`, `.xlsx`), or anything containing real names, emails, or phone numbers.
- Test fixtures must use made-up people (for example `jane.doe@example.com`).
- The `seed_data/` folders are empty on purpose. The app runs without them.

## Workflow

Work on a branch and open a pull request against `main`. Do not push to `main`
directly, and do not force-push.
