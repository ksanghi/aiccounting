"""
SMTP-based email delivery for license keys + payment receipts.

Configuration via env vars (license_server/config.py):
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
  SMTP_FROM_NAME, SMTP_USE_TLS

If SMTP_HOST is unset, send_license_email() returns False without
raising — paid orders still mint a key, you just have to look it up
manually in the orders table.

Tested with:
  - Gmail App Passwords (smtp.gmail.com:587, STARTTLS, app password as
    SMTP_PASSWORD)
  - SendGrid (smtp.sendgrid.net:587, user = "apikey", password = the
    API key)
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

from license_server.config import settings


log = logging.getLogger(__name__)


def _is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user
                and settings.smtp_password)


def send_email(
    to_email: str,
    subject:  str,
    body_text: str,
    body_html: Optional[str] = None,
) -> bool:
    """
    Send a single email. Returns True on success, False on any failure.
    Never raises — payment success path must not be aborted by a flaky
    SMTP server.
    """
    if not _is_configured():
        log.warning("Email not sent: SMTP not configured (smtp_host=%r)",
                    settings.smtp_host)
        return False
    if not to_email or "@" not in to_email:
        log.warning("Email not sent: bad address %r", to_email)
        return False

    msg = EmailMessage()
    msg["From"]    = formataddr((settings.smtp_from_name, settings.smtp_from))
    msg["To"]      = to_email
    msg["Subject"] = subject
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        if settings.smtp_use_tls:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port,
                              timeout=20) as srv:
                srv.starttls(context=ctx)
                srv.login(settings.smtp_user, settings.smtp_password)
                srv.send_message(msg)
        else:
            # SSL on connect (port 465) — Gmail also offers this.
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                  timeout=20) as srv:
                srv.login(settings.smtp_user, settings.smtp_password)
                srv.send_message(msg)
        log.info("Email sent to %s (subject=%r)", to_email, subject)
        return True
    except Exception:
        log.exception("Failed to send email to %s", to_email)
        return False


def send_license_email(
    to_email:    str,
    license_key: str,
    plan:        str,
    expires_at:  str,
    customer_name: str = "",
    amount_paid_str: str = "",
) -> bool:
    """
    Send the freshly-minted license key + activation instructions to the
    customer who just paid. Idempotent at the SMTP layer (sending twice
    just sends two emails — the *caller* should ensure it doesn't fire
    twice; webhook handler uses the order.status field to guard this).
    """
    greeting = f"Hi {customer_name}," if customer_name else "Hi,"
    receipt_line = (f"Payment received: {amount_paid_str}\n"
                    if amount_paid_str else "")

    body_text = (
        f"{greeting}\n\n"
        f"Thank you for your AccGenie purchase.\n\n"
        f"{receipt_line}"
        f"Plan:        {plan}\n"
        f"Expires:     {expires_at}\n"
        f"License key: {license_key}\n\n"
        f"To activate:\n"
        f"  1. Open AccGenie on your computer.\n"
        f"  2. Go to the License page in the left sidebar.\n"
        f"  3. Paste the key above into 'Enter license key' and click "
        f"Activate.\n\n"
        f"If you don't have AccGenie installed yet, download the latest "
        f"installer from https://accgenie.in/download.\n\n"
        f"Need help? Reply to this email or write to "
        f"info@ai-consultants.in.\n\n"
        f"— Team AccGenie\n"
    )

    body_html = f"""<!DOCTYPE html>
<html><body style="font-family: -apple-system, Segoe UI, Roboto, sans-serif;
                   color: #0F172A; max-width: 560px; margin: 0 auto;
                   padding: 24px; line-height: 1.55;">
  <p>{greeting}</p>
  <p>Thank you for your AccGenie purchase.</p>
  {f'<p style="color:#475569;">{receipt_line.strip()}</p>' if receipt_line else ''}
  <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px;
              padding: 20px; margin: 22px 0;">
    <div style="font-size: 12px; color: #6B7A99; text-transform: uppercase;
                letter-spacing: 0.08em; margin-bottom: 6px;">Your license</div>
    <div style="font-family: ui-monospace, Consolas, monospace;
                font-size: 18px; font-weight: 700; color: #635BFF;
                letter-spacing: 0.04em;">{license_key}</div>
    <div style="margin-top: 12px; font-size: 13px; color: #475569;">
      <b>Plan:</b> {plan} &nbsp;·&nbsp; <b>Expires:</b> {expires_at}
    </div>
  </div>
  <p><b>To activate:</b></p>
  <ol>
    <li>Open AccGenie on your computer.</li>
    <li>Go to the <b>License</b> page in the left sidebar.</li>
    <li>Paste the key above into <i>Enter license key</i> and click
      <b>Activate</b>.</li>
  </ol>
  <p>If you don't have AccGenie installed yet, download the latest
    installer from
    <a href="https://accgenie.in/download">accgenie.in/download</a>.</p>
  <p style="color: #475569;">Need help? Just reply to this email or
    write to <a href="mailto:info@ai-consultants.in">info@ai-consultants.in</a>.</p>
  <p style="color: #94A3B8; font-size: 12px; margin-top: 32px;">— Team AccGenie</p>
</body></html>"""

    return send_email(
        to_email=to_email,
        subject=f"Your AccGenie license — {plan}",
        body_text=body_text,
        body_html=body_html,
    )
