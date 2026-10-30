# mPower Lead-Gen — single-container image: Next.js (standalone) + FastAPI
# (uvicorn) behind Caddy, orchestrated by supervisord. One Fly machine.

# ---- Stage 1: build the Next.js frontend (standalone output) ----
FROM node:20-bookworm-slim AS frontend
WORKDIR /fe
COPY app/frontend/package.json app/frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY app/frontend/ ./
# NEXT_PUBLIC_* are baked at build time. Leave API base empty → relative URLs
# (Caddy routes /api on the same origin). Brand name is configurable per client.
ARG NEXT_PUBLIC_BRAND_NAME="mPower Lead-Gen"
ENV NEXT_PUBLIC_BRAND_NAME=${NEXT_PUBLIC_BRAND_NAME}
ENV NEXT_PUBLIC_API_BASE_URL=""
RUN npm run build

# ---- Stage 2: runtime — python backend + node frontend + caddy + supervisor ----
FROM python:3.13-slim-bookworm AS runtime
WORKDIR /app

# System deps: node runtime for the standalone server, caddy, supervisor.
RUN apt-get update \
  && apt-get install -y --no-install-recommends curl ca-certificates gnupg debian-keyring debian-archive-keyring apt-transport-https supervisor \
  && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
  && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list \
  && apt-get update && apt-get install -y --no-install-recommends caddy \
  && rm -rf /var/lib/apt/lists/*

# Backend deps.
COPY app/backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Backend source.
COPY app/backend/ /app/backend/

# Frontend standalone bundle + static + public.
COPY --from=frontend /fe/.next/standalone /app/frontend
COPY --from=frontend /fe/.next/static /app/frontend/.next/static
COPY --from=frontend /fe/public /app/frontend/public

# Caddy + supervisor config.
COPY Caddyfile /etc/caddy/Caddyfile
COPY supervisord.conf /etc/supervisor/conf.d/mpower.conf

# Persistent SQLite lives on the Fly volume mounted at /data.
ENV DATABASE_URL="sqlite+aiosqlite:////data/mpower_leadgen.db"

EXPOSE 8080
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/mpower.conf"]
