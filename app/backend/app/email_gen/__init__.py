"""S-7 email generation — AI icebreaker only.

Claude writes ONE human-sounding opening line per lead from its scraped data,
under anti-AI guardrails. The rest of the outreach is the per-campaign template
(merged at the sending slice). This module is a feature module per OP #11: it
imports only infrastructure (`jobs`, `leads`, `settings`, `db`, `campaigns`
read-only) and is imported by nothing except `main.py` (router registration).

Determinism boundary: the LLM output is stored ONLY into the non-load-bearing
`Lead.icebreaker` text field. It is never a number, never a pipeline decision.
Idempotent: a lead that already has an icebreaker is skipped (0 re-spend).
"""

from app.email_gen.router import router

__all__ = ["router"]
