"""
Razorpay client wrapper.

Wraps `razorpay.Client` so callers don't have to know about the SDK's
shape. Returns plain dicts. Raises RazorpayError on any failure (network,
auth, validation) so the endpoint handler can map to 4xx/5xx.

Configuration via env vars (see license_server/config.py):
  RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET

If key_id is unset, is_enabled() returns False — endpoints should 503
before touching this module.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

from license_server.config import settings


log = logging.getLogger(__name__)


class RazorpayError(Exception):
    pass


def is_enabled() -> bool:
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret)


def webhook_enabled() -> bool:
    return bool(settings.razorpay_webhook_secret)


def _client():
    """Lazy-import so missing SDK doesn't break server startup."""
    try:
        import razorpay  # type: ignore
    except ImportError as e:
        raise RazorpayError(
            "razorpay SDK not installed. pip install razorpay"
        ) from e
    return razorpay.Client(
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
    )


def create_order(
    amount_paise: int,
    currency:     str,
    receipt_id:   str,
    notes:        Optional[dict] = None,
) -> dict:
    """
    Create a Razorpay order. The order is what the JS Checkout uses to
    authorize a payment. Returns the order dict — important fields:
      id (str)       — pass to Razorpay Checkout JS as `order_id`
      amount (int)   — echoes amount_paise
      currency (str) — echoes currency
      status (str)   — 'created' on success
    """
    if not is_enabled():
        raise RazorpayError("Razorpay not configured (RAZORPAY_KEY_ID unset)")
    if amount_paise <= 0:
        raise RazorpayError(f"Invalid amount: {amount_paise}")
    if currency not in ("INR", "USD", "EUR", "GBP", "SGD", "AED"):
        # Razorpay supports more; restrict to what AccGenie advertises so
        # a typo in pricing.xlsx doesn't ship a wrong-currency order.
        raise RazorpayError(f"Unsupported currency: {currency}")

    try:
        order = _client().order.create(data={
            "amount":   int(amount_paise),
            "currency": currency,
            "receipt":  receipt_id,
            "notes":    notes or {},
        })
    except Exception as e:
        log.exception("Razorpay order.create failed")
        raise RazorpayError(str(e)) from e

    return order


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """
    Razorpay signs every webhook with HMAC-SHA256 of the raw request body
    using the webhook secret. Return True iff signature matches.

    The webhook secret is set by you in the Razorpay dashboard
    (Settings → Webhooks) and copied into RAZORPAY_WEBHOOK_SECRET on the
    server.
    """
    if not webhook_enabled():
        return False
    if not signature:
        return False
    try:
        expected = hmac.new(
            key=settings.razorpay_webhook_secret.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        log.exception("Razorpay signature verification crashed")
        return False
