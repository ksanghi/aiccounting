"""
Server-side pricing lookup. Reads from the baked _baked_config.py (same
source the desktop uses), so server and desktop never drift.

Why: the create-order endpoint must NOT trust price from the client —
otherwise a hacked frontend could buy PRO for ₹1. Server resolves
(plan, country_code) to (amount_paise, currency) authoritatively.
"""
from __future__ import annotations

import datetime as _dt

from license_server._baked_config import TIERS, COUNTRIES


class PricingError(Exception):
    pass


# Tier ordering for upgrade validation (higher = more features).
_TIER_RANK = {"DEMO": 0, "FREE": 1, "STANDARD": 2, "PRO": 3, "PREMIUM": 4}


def tier_rank(plan: str) -> int:
    return _TIER_RANK.get((plan or "").upper(), -1)


def compute_upgrade(product: str, current_plan: str, current_expires_at,
                    target_plan: str, country_code: str = "IN",
                    period: str = "annual", today=None) -> dict:
    """Upgrade quote, term-aware.

    upgrade_price = target's full period price − balance value of the existing
    license, floored at 0 (NO refunds). balance = current plan price × days_left
    ÷ term_days (30 monthly / 365 annual). The key is later upgraded in place to
    a fresh full term (today + term_days). Period = the license's existing term.
    """
    from license_server.plans import price_paise_for

    cur = (current_plan or "").upper()
    tgt = (target_plan or "").upper()
    period = (period or "annual").lower()
    country = (country_code or "IN").upper()

    if tier_rank(tgt) <= tier_rank(cur):
        raise PricingError(f"{tgt} is not an upgrade over {cur}")

    new_paise = price_paise_for(product, tgt, country, period)
    if not new_paise:
        raise PricingError(
            f"{tgt} is not priced for {product} ({period}) in {country}")
    cur_paise = price_paise_for(product, cur, country, period) or 0

    term_days = 30 if period == "monthly" else 365
    today = today or _dt.date.today()
    days_left = max(0, (current_expires_at - today).days)
    balance = int(round(cur_paise * days_left / term_days))
    upgrade = max(0, new_paise - balance)
    new_expiry = today + _dt.timedelta(days=term_days)

    c = _find_country(country)
    sym = (c.get("currency_symbol") if c else "") or "Rs."

    def _disp(p):
        return f"{sym} {p / 100:,.2f}"

    return {
        "product": product, "current_plan": cur, "target_plan": tgt,
        "period": period, "country_code": country, "currency_symbol": sym,
        "days_left": days_left,
        "new_full_paise": new_paise, "new_full_display": _disp(new_paise),
        "balance_paise": balance,    "balance_display": _disp(balance),
        "upgrade_paise": upgrade,    "upgrade_display": _disp(upgrade),
        "new_expiry": new_expiry.isoformat(),
    }


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
