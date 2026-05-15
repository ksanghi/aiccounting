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

Multi-product (added 2026-05-15)
================================
AccGenie (the accounting product) and RWAGenie (the RWA-vertical product
that bundles AccGenie underneath) share this server. A license carries
`product` ∈ {'accgenie', 'rwagenie'} alongside the existing plan code.

Per the operator's spec, an RWAGenie tier *inherits* the matching AG
tier's accounting features and adds RWA-specific features on top. The
feature lookup `features_for(product, plan)` returns the merged list.
This file is the single place that knows that mapping.

Pricing source: pricing.xlsx still drives AG; RWA-specific pricing is
inlined below for now (no pricing_rwa.xlsx yet). Move to a sister xlsx
once RWAGenie pricing is firm.
"""
from license_server._baked_config import (
    PLANS as _ALL_PLANS,
    PLAN_LIMITS as _ALL_PLAN_LIMITS,
    PLAN_USER_LIMITS as _ALL_PLAN_USER_LIMITS,
    PLAN_SEATS as _ALL_PLAN_SEATS,
    PLAN_FEATURES as _ALL_PLAN_FEATURES,
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
# Only the RWA-side adds. The accounting features come from PLAN_FEATURES
# above (merged in features_for() below). Tier codes match AG's so a
# customer on RWAGenie STANDARD inherits AG STANDARD's accounting set.
PLAN_FEATURES_RWA: dict[str, list[str]] = {
    "FREE": [
        "rwa_flat_ledger",
        "rwa_receipt_tracking",
        "rwa_member_directory",
        "rwa_notice_board",
        "rwa_complaint_tracking",
        "rwa_broadcast_messaging",
        "rwa_polls",
        "rwa_visitor_pass",
        "rwa_basic_reports",
    ],
    "STANDARD": [
        # FREE features carry forward
        "rwa_flat_ledger", "rwa_receipt_tracking", "rwa_member_directory",
        "rwa_notice_board", "rwa_complaint_tracking", "rwa_broadcast_messaging",
        "rwa_polls", "rwa_visitor_pass", "rwa_basic_reports",
        # STANDARD adds
        "rwa_auto_billing",
        "rwa_late_fees",
        "rwa_facilities_booking",
        "rwa_asset_register",
        "rwa_advanced_reports",
    ],
    "PRO": [
        # STANDARD features carry forward
        "rwa_flat_ledger", "rwa_receipt_tracking", "rwa_member_directory",
        "rwa_notice_board", "rwa_complaint_tracking", "rwa_broadcast_messaging",
        "rwa_polls", "rwa_visitor_pass", "rwa_basic_reports",
        "rwa_auto_billing", "rwa_late_fees", "rwa_facilities_booking",
        "rwa_asset_register", "rwa_advanced_reports",
        # PRO adds
        "rwa_whatsapp_invoices",
        "rwa_document_storage",
        "rwa_vendor_management",
    ],
    "PREMIUM": [
        # PRO features carry forward (Premium = Pro for RWA in v0.1)
        "rwa_flat_ledger", "rwa_receipt_tracking", "rwa_member_directory",
        "rwa_notice_board", "rwa_complaint_tracking", "rwa_broadcast_messaging",
        "rwa_polls", "rwa_visitor_pass", "rwa_basic_reports",
        "rwa_auto_billing", "rwa_late_fees", "rwa_facilities_booking",
        "rwa_asset_register", "rwa_advanced_reports",
        "rwa_whatsapp_invoices", "rwa_document_storage", "rwa_vendor_management",
    ],
}

# Flats per tier — analogous to PLAN_LIMITS (txn cap) for AG. None = unlimited.
PLAN_FLATS_LIMIT_RWA: dict[str, int | None] = {
    "FREE":     300,
    "STANDARD": 1000,
    "PRO":      2500,
    "PREMIUM":  None,
}

# RWAGenie-specific INR yearly prices. Drives Razorpay create-order amount.
# Per the operator's RWA features sheet: 0 / 2999 / 5999 / 14999.
PLAN_PRICES_RWA_INR: dict[str, int] = {
    "FREE":     0,
    "STANDARD": 2999,
    "PRO":      5999,
    "PREMIUM": 14999,
}

VALID_PRODUCTS = ("accgenie", "rwagenie")


def features_for(product: str, plan: str) -> list[str]:
    """
    Return the full feature list a license has, accounting for the
    AG + RWA merge convention.

    For product='accgenie': returns AG's features for the plan.
    For product='rwagenie': returns AG features (the accounting bundle
        the RWA tier inherits) ∪ RWA-specific features for the plan.

    Unknown product or plan → empty list. Caller should treat that as
    "no features" rather than crash.
    """
    plan = (plan or "").upper()
    product = (product or "accgenie").lower()
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
    combinations. Non-INR pricing for RWA isn't wired yet — falls back
    to None and the caller surfaces a friendly error."""
    plan = (plan or "").upper()
    product = (product or "accgenie").lower()
    if (country or "IN").upper() != "IN":
        # AG already has multi-country pricing in pricing.xlsx; RWA
        # currently INR-only.
        if product == "rwagenie":
            return None
    if product == "rwagenie":
        amt = PLAN_PRICES_RWA_INR.get(plan)
        return amt if amt and amt > 0 else None
    # AG pricing is handled by services.pricing_lookup.resolve_price
    # which reads pricing.xlsx — this function returns None so callers
    # know to fall through to that path.
    return None
