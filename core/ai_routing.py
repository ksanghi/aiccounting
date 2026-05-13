"""
AI routing — per-feature choice of pooled (AccGenie's Anthropic key, via our
license server proxy) vs BYOK (customer's own Anthropic key).

Stored at:
    Dev mode:  <repo>/config/ai_routing.json
    Packaged:  <user_data_dir>/config/ai_routing.json

Schema:
    {
      "own_key":  "sk-ant-...",
      "routing": {
        "document_reader":     "own"   | "pooled",
        "bank_reconciliation": "own"   | "pooled",
        "verbal_entry":        "own"   | "pooled"
      }
    }

Defaults (when a feature has never been configured):
    - bank_reconciliation → "pooled"  (low-value, high-volume)
    - document_reader / verbal_entry → "own" if own_key is set, else "pooled"

The defaults aren't written to disk until the user explicitly chooses via
the AI Routing dialog — so we can tell "user picked pooled" apart from
"never asked". `is_configured(feature)` returns True only after an
explicit choice.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from core.paths import config_dir


FEATURES = ("document_reader", "bank_reconciliation", "verbal_entry")
ROUTE_POOLED: Literal["pooled"] = "pooled"
ROUTE_OWN:    Literal["own"]    = "own"


def routing_file_path() -> Path:
    return config_dir() / "ai_routing.json"


class RoutingConfig:
    """Persistent per-feature routing + own-key store. Cheap to instantiate."""

    def __init__(self) -> None:
        self._cache: dict = self._load()

    # ── I/O ───────────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        p = routing_file_path()
        if not p.exists():
            return {"own_key": "", "routing": {}}
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"own_key": "", "routing": {}}
            data.setdefault("own_key", "")
            data.setdefault("routing", {})
            return data
        except Exception:
            return {"own_key": "", "routing": {}}

    def _save(self) -> None:
        p = routing_file_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
        except Exception:
            # Routing is a UX nicety — silently tolerate disk-full /
            # permission errors rather than crashing the AI feature.
            pass

    # ── Own key ───────────────────────────────────────────────────────────────

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

    # ── Per-feature routing ───────────────────────────────────────────────────

    def is_configured(self, feature: str) -> bool:
        """True if the user has explicitly picked a route for this feature."""
        return feature in (self._cache.get("routing") or {})

    def route_for(self, feature: str) -> str:
        """The active route. Returns 'own' or 'pooled' — never None.
        If the user hasn't configured, returns the feature's default."""
        configured = (self._cache.get("routing") or {}).get(feature)
        if configured in (ROUTE_OWN, ROUTE_POOLED):
            return configured
        # Default: high-value features prefer own key when available;
        # bulk features default to pooled.
        if feature == "bank_reconciliation":
            return ROUTE_POOLED
        return ROUTE_OWN if self.has_own_key() else ROUTE_POOLED

    def set_route(self, feature: str, route: str) -> None:
        if route not in (ROUTE_OWN, ROUTE_POOLED):
            raise ValueError(f"Invalid route: {route}")
        self._cache.setdefault("routing", {})[feature] = route
        self._save()

    def clear_route(self, feature: str) -> None:
        """Forget the user's choice — next route_for() returns the default
        and is_configured() returns False so the modal re-prompts."""
        if "routing" in self._cache and feature in self._cache["routing"]:
            del self._cache["routing"][feature]
            self._save()


# Module-level singleton for ergonomic imports.
routing = RoutingConfig()
