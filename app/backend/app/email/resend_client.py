"""Thin wrapper around the Resend Python SDK.

Read env at call time (not import time) so tests can monkeypatch per-test.
`EMAIL_ENABLED=false` short-circuits to a log-only no-op so dev/CI never hit
the network. All sender/brand values come from env so onboarding a client
domain later is a config change, not a code change.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised when Resend rejects a send. Routers catch and soft-fail."""


# Optional key resolver, registered at startup by main.py (feature→infra so
# `email` never imports `settings`). When set, it returns the resolved Resend
# key (DB-wins-when-present, env fallback). When None, we read RESEND_API_KEY
# from env directly — preserving S-1 behaviour before any key is saved.
_key_resolver: Callable[[], str | None] | None = None


def set_key_resolver(resolver: Callable[[], str | None] | None) -> None:
    global _key_resolver
    _key_resolver = resolver


def _enabled() -> bool:
    return os.environ.get("EMAIL_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


EMAIL_ENABLED = False  # re-exported for symmetry; always read fresh in send_email


def send_email(*, to: str, subject: str, html: str, text: str) -> None:
    """Send a transactional email via Resend.

    Raises `EmailDeliveryError` on any transport failure so the caller can
    surface a soft-fail (e.g. show the activation URL inline).
    """
    if not _enabled():
        logger.info(
            "[EMAIL DISABLED] would send to=%s subject=%r (set EMAIL_ENABLED=true to deliver)",
            to,
            subject,
        )
        return

    if _key_resolver is not None:
        api_key = (_key_resolver() or "").strip()
    else:
        api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        raise EmailDeliveryError("Resend API key not set while EMAIL_ENABLED=true")

    sender = os.environ.get("EMAIL_FROM", "").strip()
    if not sender:
        raise EmailDeliveryError("EMAIL_FROM not set while EMAIL_ENABLED=true")

    from_name = os.environ.get("EMAIL_FROM_NAME", "SalesPath by BuLoop AI").strip()
    from_header = f"{from_name} <{sender}>" if from_name else sender
    reply_to = os.environ.get("EMAIL_REPLY_TO", sender).strip()

    try:
        import resend  # type: ignore  # lazy — optional in test envs

        resend.api_key = api_key
        params = {
            "from": from_header,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
            "reply_to": reply_to,
        }
        resp = resend.Emails.send(params)
        logger.info("[email] sent to=%s subject=%r id=%s", to, subject, resp.get("id"))
    except EmailDeliveryError:
        raise
    except Exception as e:  # wrap any SDK / network error
        raise EmailDeliveryError(str(e)) from e
