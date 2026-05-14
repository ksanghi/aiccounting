"""
Central HTTP helper for AI calls.

Every AI feature routes through `call_messages(feature, payload)`. The
route is decided automatically by `core.ai_routing.RoutingConfig.resolve`
— there is NO user prompt and NO per-feature setting:

  "customer" — POST to api.anthropic.com with the customer's own key.
  "wallet"   — POST to the license-server /ai/proxy with the licence key;
               the server forwards to Anthropic on AccGenie's key and
               meters the customer's credit wallet.
  "locked"   — a `byok` feature, customer has no key → raise
               `FeatureNeedsOwnKey` so the calling UI can prompt them to
               add a key in Settings.

This module owns the only place we know about the Anthropic URL or the
proxy URL. Add a new AI feature → just call `call_messages(feature, ...)`
and add the feature to `core/ai_features.py`'s table.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

ANTHROPIC_URL  = "https://api.anthropic.com/v1/messages"
PROXY_URL_PATH = "/ai/proxy"   # joined with SERVER_URL at call time
ANTHROPIC_VERSION = "2023-06-01"


class AIRouteError(Exception):
    """Generic routing-or-HTTP failure the calling UI should surface."""


class FeatureNeedsOwnKey(AIRouteError):
    """A `byok` feature was used but the customer has no Anthropic key.
    The UI should prompt: 'Add your Anthropic key in Settings to use this.'"""


class AIServiceUnavailable(AIRouteError):
    """The /ai/proxy path is not configured on the licence server."""


def call_messages(feature: str, payload: dict, timeout: float = 120.0) -> dict:
    """
    Issue an Anthropic `messages` call for `feature`, routed automatically.
    Returns the parsed JSON response on success.

    Raises:
        FeatureNeedsOwnKey   — feature is `byok`, customer has no key.
        AIServiceUnavailable — wallet route, but the server proxy isn't configured.
        AIRouteError         — HTTP / network failures, out-of-credits, etc.
    """
    from core.ai_routing import (
        routing, ROUTE_CUSTOMER, ROUTE_WALLET, ROUTE_LOCKED,
    )

    route = routing.resolve(feature)

    if route == ROUTE_LOCKED:
        raise FeatureNeedsOwnKey(
            f"This feature needs your own Anthropic key. Open "
            f"Settings → AI / Anthropic Key to add one."
        )

    if route == ROUTE_CUSTOMER:
        key = routing.get_own_key() or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            # resolve() said "customer", so has_own_key() was true — this
            # only happens in a race; treat it as the locked case.
            raise FeatureNeedsOwnKey(
                "Your Anthropic key is missing. Re-add it in "
                "Settings → AI / Anthropic Key."
            )
        return _post(
            ANTHROPIC_URL,
            payload,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            timeout=timeout,
        )

    # ROUTE_WALLET — proxy through the licence server on AccGenie's key.
    from core.license_manager import LicenseManager, SERVER_URL
    mgr = LicenseManager()
    if mgr.license_key in ("DEMO", "FREE-DEMO", "", None):
        raise AIRouteError(
            "AI features on AccGenie credits need an activated paid "
            "licence. Activate your licence on the License page, or add "
            "your own Anthropic key in Settings → AI / Anthropic Key."
        )

    proxy_url = f"{SERVER_URL.rstrip('/')}{PROXY_URL_PATH}"
    headers = {
        "Content-Type":      "application/json",
        "x-license-key":     mgr.license_key,
        "x-machine-id":      mgr.get_machine_id(),
        "x-feature":         feature,
        "anthropic-version": ANTHROPIC_VERSION,
    }
    try:
        return _post(proxy_url, payload, headers=headers, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = getattr(e, "body_text", "") or ""
        # The server uses distinct, trustworthy status codes:
        #   402 → wallet out of credits
        #   503 → /ai/proxy not configured on the server
        #   502 → upstream Anthropic error (bad model, rate limit, …)
        #   401 → licence / machine binding not valid
        if e.code == 402:
            raise AIRouteError(
                "Out of AI credits — top up your AccGenie wallet to continue."
            ) from e
        if e.code == 503:
            raise AIServiceUnavailable(
                "The AI service isn't configured on the licence server yet. "
                "Contact support."
            ) from e
        raise AIRouteError(
            f"AI request failed (HTTP {e.code}): {body[:300]}"
        ) from e


def _post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    """Inner POST — same wire shape regardless of route."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            # If the response carries the proxy's metering headers, refresh
            # the local credit cache so the UI shows the right balance
            # without a separate /credits/balance round-trip.
            new_balance = resp.headers.get("x-accgenie-balance-paise")
            if new_balance is not None:
                try:
                    from ai.credit_manager import CreditManager
                    CreditManager().set_balance(int(new_balance))
                except Exception:
                    pass
            return data
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        # Stash the body on the exception so the caller can include the
        # server's message, then re-raise for the caller's HTTPError handler.
        e.body_text = err_body  # type: ignore[attr-defined]
        raise
    except urllib.error.URLError as e:
        raise AIRouteError(f"Cannot reach the AI service: {e.reason}") from e
