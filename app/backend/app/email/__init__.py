"""Email delivery module — Resend-backed sender + branded templates.

Public surface:
- `send_email(to, subject, html, text) -> None` — best-effort send. Raises
  `EmailDeliveryError` on transport failure; routers catch and surface the
  underlying URL so callers can copy-paste manually.
- `EMAIL_ENABLED` toggle: when false (default), sends are skipped + logged so
  dev/test flows work without DNS or internet.
- `templates.build_invite_email(...)` / `build_reset_email(...)` — return
  (subject, html, text) tuples.
"""

from app.email.resend_client import (
    EMAIL_ENABLED,
    EmailDeliveryError,
    send_email,
    set_key_resolver,
)

__all__ = ["EmailDeliveryError", "EMAIL_ENABLED", "send_email", "set_key_resolver"]
