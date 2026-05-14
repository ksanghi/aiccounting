"""
Central HTTP helper for AI calls.

Every AI feature in the app routes through `call_messages(feature, payload)`.
The helper looks at `core/ai_routing` for that feature, then either:

  - "own"    : POST to api.anthropic.com with the customer's BYOK key
  - "pooled" : POST to our license-server proxy with the license key
               (server forwards to Anthropic with our key and meters credits)

Until the server-side `/ai/proxy` endpoint ships (Phase 2b), the pooled
route raises `PooledNotAvailable` so the calling UI can fall back to
asking for a BYOK.

This module owns the only place we know about the Anthropic URL or the
proxy URL. Add a new AI feature → just call `call_messages(feature, ...)`.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

ANTHROPIC_URL  = "https://api.anthropic.com/v1/messages"
PROXY_URL_PATH = "/ai/proxy"   # joined with SERVER_URL at call time


class AIRouteError(Exception):
    """Generic routing-or-HTTP failure that the calling UI should surface."""


class PooledNotAvailable(AIRouteError):
    """Pooled route was selected but our server proxy isn't live yet (Phase 2b)."""


class OwnKeyMissing(AIRouteError):
    """Own-key route was selected but no Anthropic key is in routing config."""


def call_messages(
    feature: str,
    payload: dict,
    timeout: float = 120.0,
) -> dict:
    """
    Issue an Anthropic `messages` call for `feature`, routed per the user's
    AI Routing config. Returns the parsed JSON response on success.

    Raises:
        OwnKeyMissing       — route is 'own' but routing.json has no key.
        PooledNotAvailable  — route is 'pooled' but the proxy isn't live.
        AIRouteError        — HTTP / network failures with a friendly message.
    """
    from core.ai_routing import routing, ROUTE_POOLED, ROUTE_OWN

    route = routing.route_for(feature)

    if route == ROUTE_OWN:
        # Allow env-var fallback for headless / test contexts even when the
        # routing config is empty. The env var matches what document_parser
        # and voucher_ai used before this refactor.
        key = routing.get_own_key() or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise OwnKeyMissing(
                f"AI feature '{feature}' is set to use your own Anthropic key, "
                f"but no key is configured. Open Settings → AI Routing to "
                f"paste your key, or switch this feature to Pooled credits."
            )
        return _post(
            ANTHROPIC_URL,
            payload,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         key,
                "anthropic-version": "2023-06-01",
            },
            timeout=timeout,
        )

    # Pooled — proxy through our license server.
    from core.license_manager import LicenseManager, SERVER_URL
    mgr = LicenseManager()
    if mgr.license_key in ("DEMO", "FREE-DEMO", "", None):
        raise PooledNotAvailable(
            "Pooled AI credits require an activated paid license. "
            "Open Settings → AI Routing to paste your own Anthropic key, "
            "or activate a paid license on the License page."
        )

    proxy_url = f"{SERVER_URL.rstrip('/')}{PROXY_URL_PATH}"
    headers = {
        "Content-Type":      "application/json",
        "x-license-key":     mgr.license_key,
        "x-machine-id":      mgr.get_machine_id(),
        "x-feature":         feature,
        "anthropic-version": "2023-06-01",
    }
    try:
        return _post(proxy_url, payload, headers=headers, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = getattr(e, "body_text", "") or ""
        # The server (post Phase-A fix) never relays Anthropic's raw status
        # code. It uses distinct codes we can trust:
        #   402 → customer wallet is out of credits
        #   503 → /ai/proxy not configured on the server (no ANTHROPIC key)
        #   502 → upstream Anthropic error (bad model, rate limit, …)
        #   401 → license / machine binding not valid
        # A genuine 404 now only means the route truly doesn't exist (very
        # old server build) — still surface it as a real error, NOT as
        # "go use your own key".
        if e.code == 402:
            raise AIRouteError(
                "Out of AI credits — top up your AccGenie wallet to continue."
            ) from e
        if e.code == 503:
            raise PooledNotAvailable(
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
            # If the response carries our proxy's metering headers, refresh
            # the local credit cache so the UI shows the right balance
            # without an extra round-trip to /credits/balance.
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
        # Bubble the original HTTPError so callers can inspect e.code
        # (e.g. PooledNotAvailable detection above). Stash the body on it.
        e.body_text = err_body  # type: ignore[attr-defined]
        raise
    except urllib.error.URLError as e:
        raise AIRouteError(f"Cannot reach AI service: {e.reason}") from e
