"""
AccGenie pricing & tier config — operator-baked at build time.

Source of truth: `config/pricing.xlsx`. The operator edits the .xlsx,
runs `build/bake_config.py`, which writes `core/_baked_config.py`.
This module only exposes the lookup surface; nothing here reads from
disk at runtime.

Shape (see `config/pricing.xlsx` for the live data):

    TIERS = [
        {"code": "DEMO", "name": "Demo", "seats_allowed": 1,
         "txn_limit": 10, "overage_rate": 0.0, "plan_price_INR": 0,
         "notes": ""},
        ...
    ]
    PLAN_FEATURES = {"DEMO": [...], "FREE": [...], ...}
    COUNTRIES = [
        {"country_code": "IN", "currency_code": "INR",
         "tier_prices": {"DEMO": 0, "FREE": 0, "STANDARD": 1999, ...},
         "ai_text_page_cost": 0.10, "ai_scanned_page_cost": 5.00, ...},
        ...
    ]

Tier definitions are GLOBAL; per-country pricing references tier codes.
To add a new tier: append to the Tiers sheet AND add a `price_<CODE>`
column to the Countries sheet.
"""
from __future__ import annotations

from core._baked_config import TIERS, PLAN_FEATURES, COUNTRIES


# ── Country lookups ──────────────────────────────────────────────────────────

def list_active_countries() -> list[dict]:
    return [c for c in COUNTRIES if c.get("active", True)]


def get_country_pricing(country_code: str) -> dict | None:
    """Lookup by ISO-2 code (case-insensitive). None if not configured."""
    code = (country_code or "").strip().upper()
    for c in COUNTRIES:
        if c.get("country_code", "").upper() == code:
            return c
    return None


# ── Tier lookups ─────────────────────────────────────────────────────────────

def list_tiers() -> list[dict]:
    return list(TIERS)


def get_tier(tier_code: str) -> dict | None:
    """Lookup a tier definition by code. None if not configured."""
    code = (tier_code or "").strip().upper()
    for t in TIERS:
        if t.get("code", "").upper() == code:
            return t
    return None


def features_for_tier(tier_code: str) -> list[str]:
    """Return the feature_id list a tier includes."""
    return list(PLAN_FEATURES.get((tier_code or "").upper(), []))


def get_tier_price(country_code: str, tier_code: str) -> float | None:
    """
    Price (in the country's currency) for a tier in a country. None if either
    the country, the tier, or the per-country price hasn't been configured.
    """
    country = get_country_pricing(country_code)
    if not country:
        return None
    prices = country.get("tier_prices") or {}
    val = prices.get((tier_code or "").upper())
    return val if isinstance(val, (int, float)) else None
