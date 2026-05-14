"""
AI routing — decides which Anthropic key each AI call uses.

There is NO runtime user choice and NO per-feature settings dialog. The
decision is fully determined by two things:

  1. The feature's license class (`byok` | `ag_key`), from the versioned
     table in `core/ai_features.py`.
  2. Whether the customer has supplied their own Anthropic key.

`resolve(feature)` returns one of:

  "customer" — use the customer's own Anthropic key (they pay Anthropic).
  "wallet"   — use AccGenie's key via the /ai/proxy server, billed to the
               customer's credit wallet.
  "locked"   — a `byok` feature, but the customer has no key — the feature
               is unavailable until they add one.

Rules:
  - Customer HAS a key  → "customer" for EVERY feature (a customer key
    covers everything; the wallet is never touched).
  - Customer has NO key → "wallet" for `ag_key` features, "locked" for
    `byok` features.

The only thing this module persists is the customer's own key, in
`config/ai_routing.json` as `{"own_key": "sk-ant-..."}`. (The old
per-feature `routing` map is gone.)
"""
from __future__ import annotations

import json
from pathlib import Path

from core.paths import config_dir
from core.ai_features import feature_class

# resolve() return values
ROUTE_CUSTOMER = "customer"
ROUTE_WALLET   = "wallet"
ROUTE_LOCKED   = "locked"


def routing_file_path() -> Path:
    return config_dir() / "ai_routing.json"


class RoutingConfig:
    """Holds the customer's own Anthropic key (if any) and resolves the
    route for a feature. Cheap to instantiate."""

    def __init__(self) -> None:
        self._cache: dict = self._load()

    # ── I/O ───────────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        p = routing_file_path()
        if not p.exists():
            return {"own_key": ""}
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"own_key": ""}
            # Drop any legacy "routing" map silently — it's no longer used.
            return {"own_key": data.get("own_key", "") or ""}
        except Exception:
            return {"own_key": ""}

    def _save(self) -> None:
        p = routing_file_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"own_key": self._cache.get("own_key", "")},
                          f, indent=2, ensure_ascii=False)
        except Exception:
            # A key that won't persist is a UX problem, not a crash.
            pass

    def reload(self) -> None:
        self._cache = self._load()

    # ── Customer's own Anthropic key ──────────────────────────────────────────

    def get_own_key(self) -> str:
        return (self._cache.get("own_key") or "").strip()

    def has_own_key(self) -> bool:
        return bool(self.get_own_key())

    def set_own_key(self, key: str) -> None:
        self._cache["own_key"] = (key or "").strip()
        self._save()

    def clear_own_key(self) -> None:
        self._cache["own_key"] = ""
        self._save()

    # ── Routing ───────────────────────────────────────────────────────────────

    @staticmethod
    def feature_class(feature: str) -> str:
        """'byok' or 'ag_key' for a feature — from the versioned table."""
        return feature_class(feature)

    def resolve(self, feature: str) -> str:
        """Return ROUTE_CUSTOMER / ROUTE_WALLET / ROUTE_LOCKED for `feature`."""
        if self.has_own_key():
            # A customer key covers everything, heavy or light.
            return ROUTE_CUSTOMER
        # No customer key — light features fall back to the wallet,
        # heavy (byok) features are locked.
        if feature_class(feature) == "byok":
            return ROUTE_LOCKED
        return ROUTE_WALLET


# Module-level singleton for ergonomic imports.
routing = RoutingConfig()
