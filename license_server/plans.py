"""
Server-side source of truth for plan features and limits.

Baked from `config/pricing.xlsx` at build time — operator edits the .xlsx,
runs `build/bake_config.py`, which writes both `core/_baked_config.py`
(for the desktop app) and `license_server/_baked_config.py` (for this
server). This module is just a thin re-export so existing imports
(`from license_server.plans import PLANS, ...`) keep working.

The license_server side intentionally does NOT include the DEMO tier —
DEMO is a desktop-only "no key yet" trial. Server-issued keys are FREE
through PREMIUM.

Multi-product (added 2026-05-15, extended 2026-05-25)
=====================================================
Three products share this server:
  • accgenie — the accounting product
  • rwagenie — the RWA-vertical that bundles AccGenie underneath
  • tradehq  — the broker-consolidation cockpit (Phase 1 single-tier)

A license carries `product` ∈ VALID_PRODUCTS. For AG the feature list
is just AG. For RWAGenie an RWA tier inherits the matching AG tier and
adds RWA-specific features on top. For tradeHQ — single STANDARD tier,
no features gated in code yet (the desktop client doesn't call
has_feature on anything), so the feature list is empty. The licence
still binds machine seats and enforces expiry.

Pricing source: pricing.xlsx drives AG; RWA-specific pricing is
inlined below; tradeHQ pricing is TBD (still finalising). Move to
sister xlsx files once both are firm.
"""
from license_server._baked_config import (
    PLANS as _ALL_PLANS,
    PLAN_LIMITS as _ALL_PLAN_LIMITS,
    PLAN_USER_LIMITS as _ALL_PLAN_USER_LIMITS,
    PLAN_SEATS as _ALL_PLAN_SEATS,
    PLAN_FEATURES as _ALL_PLAN_FEATURES,
    # RWA HQ — now baked from the RWAHQ sheet (was hand-maintained below).
    PLAN_FEATURES_RWA as _ALL_PLAN_FEATURES_RWA,
    PLAN_FLATS_LIMIT_RWA as _ALL_PLAN_FLATS_LIMIT_RWA,
    PLAN_PRICES_RWA_INR as _ALL_PLAN_PRICES_RWA_INR,
    PLAN_PRICES_RWA_MONTHLY_INR as _ALL_PLAN_PRICES_RWA_MONTHLY_INR,
)


def _strip_demo(d):
    if isinstance(d, dict):
        return {k: v for k, v in d.items() if k != "DEMO"}
    if isinstance(d, list):
        return [x for x in d if x != "DEMO"]
    return d


# AG-side (the existing constants — unchanged behaviour for AG callers).
PLANS = _strip_demo(_ALL_PLANS)
PLAN_LIMITS = _strip_demo(_ALL_PLAN_LIMITS)
PLAN_USER_LIMITS = _strip_demo(_ALL_PLAN_USER_LIMITS)
PLAN_SEATS = _strip_demo(_ALL_PLAN_SEATS)
PLAN_FEATURES = _strip_demo(_ALL_PLAN_FEATURES)


# ── RWAGenie-specific features per tier ──────────────────────────────────────
#
# NOW BAKED from the RWAHQ sheet in config/pricing.xlsx (was hand-maintained
# here + in rwagenie/app/license_bridge.py with a "update both together" note —
# that drift trap is gone). Edit the sheet, run build/bake_config.py.
# DEMO is stripped server-side (server issues FREE..PREMIUM only).
PLAN_FEATURES_RWA: dict[str, list[str]] = _strip_demo(_ALL_PLAN_FEATURES_RWA)

# Flats per tier — analogous to PLAN_LIMITS (txn cap) for AG. None = unlimited.
PLAN_FLATS_LIMIT_RWA: dict[str, int | None] = _strip_demo(_ALL_PLAN_FLATS_LIMIT_RWA)

# RWAGenie INR prices. Annual drives the Razorpay create-order amount;
# monthly is the 11%-of-annual option surfaced at checkout.
PLAN_PRICES_RWA_INR: dict[str, int] = _strip_demo(_ALL_PLAN_PRICES_RWA_INR)
PLAN_PRICES_RWA_MONTHLY_INR: dict[str, int] = _strip_demo(_ALL_PLAN_PRICES_RWA_MONTHLY_INR)

# ── tradeHQ-specific features per tier ───────────────────────────────────────
#
# Phase 1 ships single-tier (STANDARD) with NO features gated in code —
# the desktop license_manager.has_feature() check is dormant. Keep the
# table here anyway so when tradeHQ adds metered/gated features (e.g.
# the AG-bridge ledger cleaning, broker count caps), they have a home.
PLAN_FEATURES_THQ: dict[str, list[str]] = {
    "FREE":     [],
    "STANDARD": [],
    "PRO":      [],
    "PREMIUM":  [],
}

# tradeHQ-specific INR yearly prices. Decided 2026-05-25 — small
# family head price point of Rs.200/month → Rs.2400/year. Single
# STANDARD tier covers the whole app for now.
PLAN_PRICES_THQ_INR: dict[str, int | None] = {
    "FREE":     0,
    "STANDARD": 2400,
    "PRO":      None,
    "PREMIUM":  None,
}


VALID_PRODUCTS = ("accgenie", "rwagenie", "tradehq")


def features_for(product: str, plan: str) -> list[str]:
    """
    Return the full feature list a license has, accounting for the
    AG + RWA merge convention.

    For product='accgenie': returns AG's features for the plan.
    For product='rwagenie': returns AG features (the accounting bundle
        the RWA tier inherits) ∪ RWA-specific features for the plan.
    For product='tradehq':  returns tradeHQ features only — tradeHQ is
        standalone (does NOT inherit AG accounting features).

    Unknown product or plan → empty list. Caller should treat that as
    "no features" rather than crash.
    """
    plan = (plan or "").upper()
    product = (product or "accgenie").lower()
    if product == "tradehq":
        return list(PLAN_FEATURES_THQ.get(plan, []))
    ag = PLAN_FEATURES.get(plan, [])
    if product == "rwagenie":
        rwa = PLAN_FEATURES_RWA.get(plan, [])
        # Preserve order: accounting features first (predictable for UI),
        # then RWA features. De-dupe in case future edits introduce overlap.
        seen: set[str] = set()
        merged: list[str] = []
        for f in list(ag) + list(rwa):
            if f not in seen:
                seen.add(f)
                merged.append(f)
        return merged
    return list(ag)


def flats_limit_for(plan: str) -> int | None:
    """Per-tier flat cap for RWAGenie. Only meaningful when product=rwagenie."""
    return PLAN_FLATS_LIMIT_RWA.get((plan or "").upper())


def price_for(product: str, plan: str, country: str = "IN") -> int | None:
    """INR price for (product, plan). Used to size Razorpay orders.
    Returns None for FREE plans (skip checkout entirely) or unknown
    combinations. Non-INR pricing for RWA / tradeHQ isn't wired yet —
    falls back to None and the caller surfaces a friendly error."""
    plan = (plan or "").upper()
    product = (product or "accgenie").lower()
    if (country or "IN").upper() != "IN":
        # AG already has multi-country pricing in pricing.xlsx; RWA and
        # tradeHQ are currently INR-only.
        if product in ("rwagenie", "tradehq"):
            return None
    if product == "rwagenie":
        amt = PLAN_PRICES_RWA_INR.get(plan)
        return amt if amt and amt > 0 else None
    if product == "tradehq":
        amt = PLAN_PRICES_THQ_INR.get(plan)
        return amt if amt and amt > 0 else None
    # AG pricing is handled by services.pricing_lookup.resolve_price
    # which reads pricing.xlsx — this function returns None so callers
    # know to fall through to that path.
    return None
