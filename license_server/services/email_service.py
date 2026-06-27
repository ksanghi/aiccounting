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


def _mkt_cfg() -> dict:
    """Marketing sender config — a SEPARATE relay/identity (Brevo + the
    mail.<domain> subdomain) so a cold blast can't touch the transactional
    sender. Falls back to the main smtp_* config if mkt_* is unset."""
    s = settings
    return {
        "host":      s.mkt_smtp_host or s.smtp_host,
        "port":      s.mkt_smtp_port or s.smtp_port,
        "user":      s.mkt_smtp_user or s.smtp_user,
        "password":  s.mkt_smtp_password or s.smtp_password,
        "from":      s.mkt_smtp_from or s.smtp_from,
        "from_name": s.mkt_smtp_from_name or s.smtp_from_name,
        "use_tls":   s.mkt_smtp_use_tls,
    }


def _connect(cfg: dict):
    """Open + authenticate one SMTP connection for the given config. Raises."""
    if cfg["use_tls"]:
        ctx = ssl.create_default_context()
        srv = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
        srv.starttls(context=ctx)
    else:
        srv = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30)
    srv.login(cfg["user"], cfg["password"])
    return srv


def send_bulk(messages, reconnect_every: int = 50, throttle: float = 0.1):
    """Send many emails over a REUSED SMTP connection (far more robust than a
    fresh connect per message, which shared relays rate-limit).

    `messages` is an iterable of (to_email, subject, body_text, body_html).
    Reconnects every `reconnect_every` sends and after any error. Yields
    (to_email, ok: bool) per message. Never raises — a single bad recipient
    or a dropped connection doesn't abort the batch.
    """
    import time as _time
    cfg = _mkt_cfg()                       # marketing relay (Brevo + subdomain)
    if not (cfg["host"] and cfg["user"] and cfg["password"]):
        for m in messages:
            yield (m[0], False)
        return
    srv = None
    on_conn = 0
    for to_email, subject, body_text, body_html in messages:
        if not to_email or "@" not in to_email:
            yield (to_email, False)
            continue
        try:
            if srv is None or on_conn >= reconnect_every:
                if srv is not None:
                    try: srv.quit()
                    except Exception: pass
                srv = _connect(cfg)
                on_conn = 0
            msg = EmailMessage()
            msg["From"]    = formataddr((cfg["from_name"], cfg["from"]))
            msg["To"]      = to_email
            msg["Subject"] = subject
            msg.set_content(body_text)
            if body_html:
                msg.add_alternative(body_html, subtype="html")
            srv.send_message(msg)
            on_conn += 1
            if throttle:
                _time.sleep(throttle)
            yield (to_email, True)
        except Exception:
            log.exception("bulk send failed for %s", to_email)
            try:
                if srv: srv.quit()
            except Exception: pass
            srv = None          # force reconnect on the next message
            yield (to_email, False)
    if srv is not None:
        try: srv.quit()
        except Exception: pass


# India display names for each internal product code. See
# memory project-product-branding.md — country-driven branding; this
# table is the email-side India view. When US pack ships, swap based
# on country.
_PRODUCT_DISPLAY_IN = {
    "accgenie": "Accounts HQ",
    "rwagenie": "RWA HQ",
    "tradehq":  "tradeHQ",
}


# Public installer URL per product. Only RWA HQ has a real installer in
# marketing/downloads/ today; the others fall through to a "write to info@"
# nudge until their installers land.
_INSTALLER_URL = {
    "rwagenie": "https://apps.ai-consultants.in/downloads/RWAHQ-Setup.exe",
    "accgenie": "https://apps.ai-consultants.in/downloads/AccountsHQ-Setup.exe",
}


def send_license_email(
    to_email:    str,
    license_key: str,
    plan:        str,
    expires_at:  str,
    customer_name: str = "",
    amount_paid_str: str = "",
    product:     str = "accgenie",
) -> bool:
    """
    Send the freshly-minted license key + activation instructions to the
    customer who just paid. Idempotent at the SMTP layer (sending twice
    just sends two emails — the *caller* should ensure it doesn't fire
    twice; webhook handler uses the order.status field to guard this).
    """
    product_name = _PRODUCT_DISPLAY_IN.get(
        (product or "accgenie").lower(), "the software"
    )
    # Sign with whoever the SMTP envelope is from, so the signature
    # tracks brand changes without a code edit. Defaults gracefully
    # when SMTP_FROM_NAME isn't set.
    signer = (settings.smtp_from_name or "").strip() or "AI Consultants"
    is_free = (plan or "").upper() == "FREE"

    greeting = f"Hi {customer_name}," if customer_name else "Hi,"
    receipt_line = (f"Payment received: {amount_paid_str}\n"
                    if amount_paid_str else "")
    thanks_line = (
        f"Thank you for trying {product_name}." if is_free
        else f"Thank you for your {product_name} purchase."
    )
    installer_url = _INSTALLER_URL.get((product or "").lower(), "")
    if installer_url:
        installer_line_text = (
            f"If you don't have {product_name} installed yet, download "
            f"it here:\n  {installer_url}\n\n"
        )
        installer_line_html = (
            f'<p>If you don\'t have {product_name} installed yet, '
            f'<a href="{installer_url}">download the installer</a>.</p>'
        )
    else:
        installer_line_text = (
            f"If you don't have {product_name} installed yet, write to "
            f"info@ai-consultants.in for the latest installer.\n\n"
        )
        installer_line_html = (
            f'<p>If you don\'t have {product_name} installed yet, write to '
            f'<a href="mailto:info@ai-consultants.in">info@ai-consultants.in</a> '
            f'for the latest installer.</p>'
        )

    body_text = (
        f"{greeting}\n\n"
        f"{thanks_line}\n\n"
        f"{receipt_line}"
        f"Plan:        {plan}\n"
        f"Expires:     {expires_at}\n"
        f"License key: {license_key}\n\n"
        f"To activate:\n"
        f"  1. Open {product_name} on your computer.\n"
        f"  2. Go to the License page in the left sidebar.\n"
        f"  3. Paste the key above into 'Enter license key' and click "
        f"Activate.\n\n"
        f"{installer_line_text}"
        f"Need help? Reply to this email or write to "
        f"info@ai-consultants.in.\n\n"
        f"— {signer}\n"
    )

    body_html = f"""<!DOCTYPE html>
<html><body style="font-family: -apple-system, Segoe UI, Roboto, sans-serif;
                   color: #0F172A; max-width: 560px; margin: 0 auto;
                   padding: 24px; line-height: 1.55;">
  <p>{greeting}</p>
  <p>{thanks_line}</p>
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
    <li>Open {product_name} on your computer.</li>
    <li>Go to the <b>License</b> page in the left sidebar.</li>
    <li>Paste the key above into <i>Enter license key</i> and click
      <b>Activate</b>.</li>
  </ol>
  {installer_line_html}
  <p style="color: #475569;">Need help? Just reply to this email or
    write to <a href="mailto:info@ai-consultants.in">info@ai-consultants.in</a>.</p>
  <p style="color: #94A3B8; font-size: 12px; margin-top: 32px;">— {signer}</p>
</body></html>"""

    return send_email(
        to_email=to_email,
        subject=f"Your {product_name} license — {plan}",
        body_text=body_text,
        body_html=body_html,
    )
