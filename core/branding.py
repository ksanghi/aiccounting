"""
Product branding — the user-facing name + logo, set ONCE here and read by the
SHARED base UI so AHQ and RHQ each show their own brand from the same code.

  AHQ (Accounts HQ) : the defaults below.
  RHQ (RWA HQ)      : overrides these at startup — rwagenie/app/main.py does
                      `from core import branding; branding.PRODUCT_NAME = "RWA HQ"`
                      (and points logo_file at its own logo) BEFORE any window
                      is built.

IMPORTANT: shared modules must read `branding.PRODUCT_NAME` AT CALL TIME
(`from core import branding; ... branding.PRODUCT_NAME ...`) — NOT
`from core.branding import PRODUCT_NAME` — so a runtime override is seen.

NOTE: this is the DISPLAY name only. The per-user DATA FOLDER name lives in
core.paths (APP_NAME = "AccGenie") and is deliberately NOT renamed — changing
it would orphan every existing user's companies on disk.
"""
from __future__ import annotations

import os

# User-facing product name. RHQ overrides at startup.
PRODUCT_NAME = "Accounts HQ"

# Brand logo filename under ui/ (splash, window icon, sidebar). RHQ overrides.
logo_file = "accountshq-logo.png"


def logo_path() -> str:
    """Absolute path to the current brand logo bundled under ui/."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ui", logo_file,
    )
