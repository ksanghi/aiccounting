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


PLANS = _strip_demo(_ALL_PLANS)
PLAN_LIMITS = _strip_demo(_ALL_PLAN_LIMITS)
PLAN_USER_LIMITS = _strip_demo(_ALL_PLAN_USER_LIMITS)
PLAN_SEATS = _strip_demo(_ALL_PLAN_SEATS)
PLAN_FEATURES = _strip_demo(_ALL_PLAN_FEATURES)
