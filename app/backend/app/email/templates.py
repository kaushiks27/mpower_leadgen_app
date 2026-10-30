"""Branded email body builders for invite / reset flows.

Return `(subject, html, text)`. HTML is single-file inline-style (no Jinja) so
it inlines safely past Gmail/Outlook style stripping. The brand name is read
from `APP_BRAND_NAME` (default "mPower Lead-Gen") so onboarding a client is a
config change, not a code change.
"""

from __future__ import annotations

import os

_BRAND_ORANGE = "#F26522"  # mPower industrial orange (matches UI accent)
_BRAND_INK = "#1C1F26"


def _brand_name() -> str:
    return (
        os.environ.get("APP_BRAND_NAME", "SalesPath by BuLoop AI").strip()
        or "SalesPath by BuLoop AI"
    )


def _html_shell(*, headline: str, body_html: str, button_label: str, button_url: str) -> str:
    brand = _brand_name()
    initial = (brand[:1] or "M").upper()
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#F5F4F2;font-family:Inter,Helvetica,Arial,sans-serif;color:{_BRAND_INK};">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F5F4F2;padding:32px 16px;">
    <tr><td align="center">
      <table width="540" cellpadding="0" cellspacing="0" border="0" style="background:#fff;border-radius:20px;padding:32px;max-width:540px;">
        <tr><td>
          <table cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td style="background:{_BRAND_ORANGE};width:36px;height:36px;border-radius:8px;text-align:center;vertical-align:middle;">
                <span style="color:#fff;font-weight:700;font-size:14px;">{initial}</span>
              </td>
              <td style="padding-left:10px;font-weight:600;font-size:15px;">{brand}</td>
            </tr>
          </table>
          <h1 style="font-size:23px;font-weight:600;margin:24px 0 12px;color:{_BRAND_INK};">{headline}</h1>
          <div style="font-size:15px;line-height:1.55;color:#4A4F58;">{body_html}</div>
          <p style="margin:28px 0 8px;">
            <a href="{button_url}" style="display:inline-block;background:{_BRAND_ORANGE};color:#fff;text-decoration:none;font-weight:600;padding:12px 22px;border-radius:10px;font-size:14px;">{button_label}</a>
          </p>
          <p style="font-size:12px;color:#9099A4;margin-top:20px;word-break:break-all;">
            or copy this link: <br><span style="font-family:'SFMono-Regular',Menlo,monospace;">{button_url}</span>
          </p>
        </td></tr>
      </table>
      <p style="font-size:11px;color:#9099A4;margin-top:18px;">{brand} · sales pipeline</p>
    </td></tr>
  </table>
</body></html>"""


def build_invite_email(*, activate_url: str, invitee_email: str) -> tuple[str, str, str]:
    brand = _brand_name()
    subject = f"You've been invited to {brand}"
    html = _html_shell(
        headline="You've been invited",
        body_html=(
            f"You ({invitee_email}) have been invited to use {brand}. "
            "Click below to set your password and activate your account."
        ),
        button_label="Activate account",
        button_url=activate_url,
    )
    text = (
        f"You ({invitee_email}) have been invited to {brand}.\n\n"
        f"Activate your account: {activate_url}\n\n"
        "This link expires in 7 days."
    )
    return subject, html, text


def build_invite_reminder_email(
    *, activate_url: str, invitee_email: str
) -> tuple[str, str, str]:
    subject, html, text = build_invite_email(
        activate_url=activate_url, invitee_email=invitee_email
    )
    subject = f"Your {_brand_name()} invite (reminder)"
    return subject, html, text


def build_reset_email(*, reset_url: str, recipient_email: str) -> tuple[str, str, str]:
    brand = _brand_name()
    subject = f"Reset your {brand} password"
    html = _html_shell(
        headline="Reset your password",
        body_html=(
            f"Someone (hopefully you) requested a password reset for {recipient_email}. "
            "Click below to choose a new password. If you didn't request this, ignore "
            "this email — your password won't change."
        ),
        button_label="Reset password",
        button_url=reset_url,
    )
    text = (
        f"Password reset requested for {recipient_email}.\n\n"
        f"Reset link: {reset_url}\n\n"
        "This link expires in 1 hour. Ignore if you didn't request it."
    )
    return subject, html, text
