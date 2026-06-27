"""
DEV-ONLY launcher — force Books HQ (US) mode without a real US licence, so we
can eyeball the US surface ($ / Sales Tax / 1099 / Schedule C / Mileage / brand).

NOT shipped. Run:  python dev_us.py
"""
from core import country, branding
from core.license_manager import LicenseManager

# Pin the US CountryProfile and keep it pinned through the background licence
# re-validation (which would otherwise reset_active() back to the licence country).
country.set_active("US")
country.reset_active = lambda: None

# Dev god-mode: unlock every feature so the PRO-gated US screens are visible.
LicenseManager.has_feature = lambda self, fid: True

# Name + logo + icon -> Books HQ (before main computes LOGO_PATH at import).
branding.apply_country_branding()

import main  # noqa: E402
main.main()
