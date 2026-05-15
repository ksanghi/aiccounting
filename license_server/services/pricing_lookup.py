"""
Server-side pricing lookup. Reads from the baked _baked_config.py (same
source the desktop uses), so server and desktop never drift.

Why: the create-order endpoint must NOT trust price from the client —
otherwise a hacked frontend could buy PRO for ₹1. Server resolves
(plan, country_code) to (amount_paise, currency) authoritatively.
"""
from __future__ import annotations

from license_server._baked_config import TIERS, COUNTRIES


class PricingError(Exception):
    pass


def _find_country(country_code: str) -> dict | None:
    code = (country_code or "").strip().upper()
    for c in COUNTRIES:
        if c.get("country_code", "").upper() == code:
            return c
    return None


def _find_tier(plan: str) -> dict | None:
    plan = (plan or "").strip().upper()
    for t in TIERS:
        if t.get("code", "").upper() == plan:
            return t
    return None


def resolve_price(plan: str, country_code: str = "IN") -> dict:
    """
    Resolve (plan, country) → {amount_paise, currency, currency_symbol,
    country_code, plan_code, plan_name}.

    Raises PricingError if the plan doesn't exist, the country isn't
    configured, the country isn't active, or the plan isn't priced in
    that country (tier_prices[plan] is null).

    DEMO and FREE are always priceable at 0 in any active country —
    those tiers exist on the marketing page but the checkout flow
    rejects them with PricingError (don't create a Razorpay order for
    ₹0; just let the customer download the free plan directly).
    """
    tier = _find_tier(plan)
    if tier is None:
        raise PricingError(f"Unknown plan: {plan}")

    country = _find_country(country_code)
    if country is None:
        raise PricingError(f"Country not configured: {country_code}")
    if not country.get("active", True):
        raise PricingError(f"Country not active: {country_code}")

    plan_code = tier["code"]
    currency  = country.get("currency_code") or "INR"
    tier_prices = country.get("tier_prices") or {}
    raw = tier_prices.get(plan_code)
    if raw is None:
        raise PricingError(
            f"Plan {plan_code} is not priced in {country_code}"
        )
    if not isinstance(raw, (int, float)) or raw <= 0:
        raise PricingError(
            f"Plan {plan_code} has zero or invalid price in {country_code}: "
            f"{raw!r} — DEMO/FREE shouldn't go through checkout."
        )

    # All Razorpay-supported currencies use 2-decimal minor units except
    # JPY/KRW. AccGenie's advertised currencies (INR, USD, EUR, GBP, SGD,
    # AED) are all 2-decimal, so amount_paise == price × 100.
    amount_paise = int(round(float(raw) * 100))

    return {
        "plan_code":       plan_code,
        "plan_name":       tier.get("name", plan_code),
        "currency":        currency,
        "currency_symbol": country.get("currency_symbol", ""),
        "country_code":    country.get("country_code", country_code).upper(),
        "country_name":    country.get("country_name", country_code),
        "amount_paise":    amount_paise,
        "amount_display":  f"{country.get('currency_symbol','')} {float(raw):,.2f}".strip(),
    }
