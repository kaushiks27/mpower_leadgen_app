"""Pure, deterministic app-campaign → Instantly-v2 payload transforms.

No network, no DB, no float, no LLM. Same input → same output. Every load-bearing
mapping (schedule day-index, send window, sequence step gaps, placeholder remap)
lives here so it is unit-tested against fixtures in isolation.

Instantly v2 reference (verified 2026-06-03):
- POST /api/v2/campaigns: { name, campaign_schedule: { schedules: [{ name, timing:
  { from:"HH:MM", to:"HH:MM" }, days: { "0".."6": bool }, timezone }] },
  sequences: [{ steps: [{ type:"email", delay:int, variants:[{ subject, body }] }] }] }
  days keys: "0"=Sunday … "6"=Saturday. body is HTML.
- POST /api/v2/leads: { campaign, email, first_name, last_name, company_name,
  custom_variables: { ... } }

The body is sent word-for-word: only newlines become <br> and the app's single-
brace placeholders are remapped to Instantly's double-brace merge tags so Instantly
fills the SAME values (icebreaker pushed per-lead as a custom variable).
"""

from __future__ import annotations

import html

# app SEND_DAYS weekday name -> Instantly days-object key ("0"=Sun..="6"=Sat).
_DAY_TO_INDEX = {
    "sun": "0",
    "mon": "1",
    "tue": "2",
    "wed": "3",
    "thu": "4",
    "fri": "5",
    "sat": "6",
}

# Instantly's schedule `timezone` enum is the CANONICAL IANA set (its docs example
# is `America/Chicago`). The app's S-3 timezone picker can store DEPRECATED IANA
# aliases (e.g. India saved as `Asia/Calcutta`), which Instantly rejects with a
# 400. Normalize the known deprecated aliases to their canonical name before the
# push; pass-through for zones already canonical.
_TZ_ALIASES = {
    "Asia/Calcutta": "Asia/Kolkata",       # India (the mPower default)
    "Asia/Rangoon": "Asia/Yangon",
    "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Asia/Katmandu": "Asia/Kathmandu",
    "Europe/Kiev": "Europe/Kyiv",
    "America/Godthab": "America/Nuuk",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
}


def to_instantly_timezone(tz: str) -> str:
    """Deprecated IANA alias -> canonical name (Instantly's enum). Verbatim when
    the zone is already canonical."""
    return _TZ_ALIASES.get((tz or "").strip(), tz)


# app single-brace placeholder -> Instantly double-brace merge tag. Standard
# Instantly fields use firstName/companyName; icebreaker is a per-lead custom var.
_PLACEHOLDERS = {
    "{icebreaker}": "{{icebreaker}}",
    "{first_name}": "{{firstName}}",
    "{company}": "{{companyName}}",
}


def remap_placeholders(text: str) -> str:
    """Translate the app's `{chip}` tags to Instantly `{{merge}}` tags. Verbatim
    otherwise — no other character is touched."""
    out = text or ""
    for src, dst in _PLACEHOLDERS.items():
        out = out.replace(src, dst)
    return out


def to_html(text: str) -> str:
    """Plain-text body -> minimal HTML. Newlines become <br>; text is HTML-escaped
    so it renders literally; merge tags ({{...}}) survive escaping unchanged."""
    escaped = html.escape(text or "", quote=False)
    return escaped.replace("\n", "<br>\n")


def _body_html(text: str) -> str:
    """Remap placeholders first (so {{...}} braces aren't escaped), then HTML-ify."""
    return to_html(remap_placeholders(text))


def _timing(hour: int) -> str:
    """0..23 int hour -> 'HH:00' (deterministic, zero-padded)."""
    return f"{int(hour):02d}:00"


def to_days_object(send_days_csv: str) -> dict[str, bool]:
    """CSV of app weekday names -> Instantly days object {"0".."6": bool}.

    Output keys are always the full 0..6 set (unlisted days = False), in canonical
    Sunday-first order for stable serialization.
    """
    active = {d.strip().lower() for d in (send_days_csv or "").split(",") if d.strip()}
    return {idx: (name in active) for name, idx in sorted(_DAY_TO_INDEX.items(), key=lambda kv: kv[1])}


def to_sequence_steps(steps: list) -> list[dict]:
    """Ordered app steps -> Instantly sequence steps.

    App `wait_days` = days to wait BEFORE a step (step 1 = 0 = immediate).
    Instantly step `delay` = days to wait AFTER a step before the next one. So
    Instantly delay[i] = app wait_days[i+1]; the last step's delay = 0.
    Steps are taken in `step_order` (assumed pre-sorted by the caller's query).
    """
    ordered = list(steps)
    out: list[dict] = []
    for i, step in enumerate(ordered):
        next_wait = ordered[i + 1].wait_days if i + 1 < len(ordered) else 0
        out.append(
            {
                "type": "email",
                "delay": int(next_wait),
                "variants": [
                    {
                        "subject": remap_placeholders(step.subject),
                        "body": _body_html(step.body),
                    }
                ],
            }
        )
    return out


def to_campaign_payload(campaign, steps: list) -> dict:
    """Build the POST /api/v2/campaigns body from an app campaign + its steps."""
    return {
        "name": campaign.name,
        "campaign_schedule": {
            "schedules": [
                {
                    "name": "Schedule",
                    "timing": {
                        "from": _timing(campaign.send_start_hour),
                        "to": _timing(campaign.send_end_hour),
                    },
                    "days": to_days_object(campaign.send_days),
                    "timezone": to_instantly_timezone(campaign.timezone),
                }
            ]
        },
        "sequences": [{"steps": to_sequence_steps(steps)}],
    }


def to_lead_payload(lead) -> dict:
    """Build one lead entry for the bulk POST /api/v2/leads/add `leads` array.

    No campaign field here — the batch carries `campaign_id` at the top level.
    The icebreaker rides as a custom variable so the sequence's {{icebreaker}}
    merge tag fills that lead's exact stored line; native first_name/company_name
    resolve {{firstName}}/{{companyName}}.
    """
    company_name = lead.company.name if lead.company else ""
    return {
        "email": lead.email,
        "first_name": lead.first_name or "",
        "last_name": lead.last_name or "",
        "company_name": company_name,
        "personalization": lead.icebreaker or "",
        "custom_variables": {"icebreaker": lead.icebreaker or ""},
    }
