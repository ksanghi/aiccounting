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

# Brand logo filename under ui/ (splash, sidebar wordmark). RHQ overrides.
logo_file = "accountshq-logo.png"

# Square app icon (.ico) for the window / taskbar. A wide wordmark squishes as
# a window icon, so this is a dedicated square mark. RHQ overrides at startup.
icon_file = "accountshq.ico"


def apply_country_branding() -> None:
    """Accounts HQ and Books HQ are the SAME build — the licensed country picks
    the brand. Call ONCE at startup, after the licence/country is resolved and
    BEFORE any window is built. A US licence → "Books HQ" with its own wordmark
    + icon. RHQ sets its own brand and never calls this."""
    global PRODUCT_NAME, logo_file, icon_file
    try:
        from core import country
        if country.active_profile().tax_system == "US_SALES_TAX":
            PRODUCT_NAME = "Books HQ"
            logo_file = "bookshq-logo.png"
            icon_file = "bookshq.ico"
    except Exception:
        pass


def logo_path() -> str:
    """Absolute path to the current brand logo bundled under ui/."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ui", logo_file,
    )


def icon_path() -> str:
    """Absolute path to the current square app icon bundled under ui/."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ui", icon_file,
    )
