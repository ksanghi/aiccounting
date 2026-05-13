"""
AccGenie pricing & tier config — a plain JSON file the operator edits by hand.

Location:
    Dev mode:     <repo>/config/pricing.json
    Packaged:     %APPDATA%/AccGenie/config/pricing.json  (Win)
                  ~/Library/Application Support/AccGenie/config/pricing.json  (mac)
                  ~/.local/share/AccGenie/config/pricing.json  (Linux)

`ensure_pricing_file()` seeds the file on first run. After that it NEVER
overwrites — edit the file directly to add tiers / countries / update prices.

File shape (see config/pricing.json for the live example):

    {
      "tiers": [
        {"code": "DEMO", "name": "Demo", "seats_allowed": 1,
         "voucher_limit": 10, "features": [...], "notes": ""},
        ...
      ],
      "countries": [
        {
          "country_code":   "IN",
          "country_name":   "India",
          "currency_code":  "INR",
          "currency_symbol":"₹",
          "tier_prices":    { "DEMO": 0, "SILVER": 1999, ... },
          "ai_text_page_cost":       0.10,
          "ai_scanned_page_cost":    5.00,
          "ai_per_transaction_cost": null,
          "active":         true,
          "notes":          ""
        },
        ...
      ]
    }

Tier definitions are GLOBAL (one source of truth). Per-country pricing
references tier codes. To add a new tier: append to "tiers" AND add the
new code to every country's "tier_prices" map.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.paths import config_dir


def pricing_file_path() -> Path:
    return config_dir() / "pricing.json"


_SEED: dict = {
    "_comment": (
        "AccGenie pricing & tier config. Edit freely; the app never "
        "overwrites this file once it exists. Two sections: 'tiers' "
        "defines plan structure (name, seats, voucher limits, features) "
        "and is global. 'countries' defines per-country currency + "
        "tier_prices map (key = tier 'code'). Add a new country by "
        "appending to 'countries'. Add a new tier by appending to "
        "'tiers' and adding its price under each country's 'tier_prices'. "
        "Use null for tiers not offered in a country."
    ),
    "tiers": [
        {
            "code": "DEMO",
            "name": "Demo",
            "seats_allowed": 1,
            "voucher_limit": 10,
            "features": [
                "vouchers", "daybook", "ledger_balances", "reports",
                "export_excel", "export_pdf",
                "bank_reconciliation", "ledger_reconciliation",
                "book_migration", "backup", "gst", "tds",
                "ai_document_reader", "verbal_entry", "auto_billing",
            ],
            "notes": "Full-feature trial, hard-capped at voucher_limit.",
        },
        {
            "code": "SILVER", "name": "Silver",
            "seats_allowed": None, "voucher_limit": None,
            "features": [],
            "notes": "Fill seats_allowed, voucher_limit, features.",
        },
        {
            "code": "GOLD", "name": "Gold",
            "seats_allowed": None, "voucher_limit": None,
            "features": [],
            "notes": "Fill seats_allowed, voucher_limit, features.",
        },
        {
            "code": "PREMIUM", "name": "Premium",
            "seats_allowed": None, "voucher_limit": None,
            "features": [],
            "notes": "Fill seats_allowed, voucher_limit, features.",
        },
    ],
    "countries": [
        {
            "country_code":            "IN",
            "country_name":            "India",
            "currency_code":           "INR",
            "currency_symbol":         "₹",
            "tier_prices":             {"DEMO": 0, "SILVER": None,
                                        "GOLD": None, "PREMIUM": None},
            "ai_text_page_cost":       0.10,
            "ai_scanned_page_cost":    5.00,
            "ai_per_transaction_cost": None,
            "active":                  True,
            "notes":                   "Home market. Prices in INR per month.",
        },
        {
            "country_code":            "US",
            "country_name":            "United States",
            "currency_code":           "USD",
            "currency_symbol":         "$",
            "tier_prices":             {"DEMO": 0, "SILVER": None,
                                        "GOLD": None, "PREMIUM": None},
            "ai_text_page_cost":       None,
            "ai_scanned_page_cost":    None,
            "ai_per_transaction_cost": None,
            "active":                  True,
            "notes":                   "Fill USD prices.",
        },
        {
            "country_code":            "SG",
            "country_name":            "Singapore",
            "currency_code":           "SGD",
            "currency_symbol":         "S$",
            "tier_prices":             {"DEMO": 0, "SILVER": None,
                                        "GOLD": None, "PREMIUM": None},
            "ai_text_page_cost":       None,
            "ai_scanned_page_cost":    None,
            "ai_per_transaction_cost": None,
            "active":                  True,
            "notes":                   "Fill SGD prices.",
        },
        {
            "country_code":            "AE",
            "country_name":            "United Arab Emirates",
            "currency_code":           "AED",
            "currency_symbol":         "AED",
            "tier_prices":             {"DEMO": 0, "SILVER": None,
                                        "GOLD": None, "PREMIUM": None},
            "ai_text_page_cost":       None,
            "ai_scanned_page_cost":    None,
            "ai_per_transaction_cost": None,
            "active":                  True,
            "notes":                   "Fill AED prices.",
        },
    ],
}


def ensure_pricing_file() -> Path:
    """Seed pricing.json on first run. Never overwrites an existing file."""
    p = pricing_file_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(_SEED, f, indent=2, ensure_ascii=False)
    return p


def _load() -> dict:
    p = pricing_file_path()
    if not p.exists():
        ensure_pricing_file()
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"tiers": [], "countries": []}


# ── Country lookups ──────────────────────────────────────────────────────────

def list_active_countries() -> list[dict]:
    return [c for c in _load().get("countries", []) if c.get("active", True)]


def get_country_pricing(country_code: str) -> dict | None:
    """Lookup by ISO-2 code (case-insensitive). None if not configured."""
    code = (country_code or "").strip().upper()
    for c in _load().get("countries", []):
        if c.get("country_code", "").upper() == code:
            return c
    return None


# ── Tier lookups ─────────────────────────────────────────────────────────────

def list_tiers() -> list[dict]:
    return _load().get("tiers", [])


def get_tier(tier_code: str) -> dict | None:
    """Lookup a tier definition by code. None if not configured."""
    code = (tier_code or "").strip().upper()
    for t in _load().get("tiers", []):
        if t.get("code", "").upper() == code:
            return t
    return None


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
