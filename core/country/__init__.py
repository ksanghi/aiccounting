"""
Country profiles — the country-aware layer (A13).

A licence is issued for one country (`License.country_code`, surfaced
on the desktop as `LicenseManager.country`). That country selects a
`CountryProfile`, which declares everything country-specific in one
place: the tax system, which tax screens exist, the currency, the
date format, and the tax-registration field label.

Design (agreed 2026-05-21):
  • COUNTRY gates laws / screens / locale.  TIER still gates features.
    The two axes are orthogonal — don't fold country into the
    pricing.xlsx tier matrix.
  • One build ships every country pack; the licence activates one.
  • India is the only real pack today; it encodes current behaviour
    exactly, so routing through this registry is a zero-change move.
    Other packs (A13a US, A13b further) are added later as isolated
    modules — an unknown / not-yet-built country falls back to India
    so the app never crashes on a country it doesn't have a pack for.

Usage:
    from core import country
    prof = country.active_profile()      # from the licence
    prof = country.get_profile("US")     # explicit lookup
"""
from __future__ import annotations

from core.country.base  import CountryProfile
from core.country.india import INDIA


# Registry — ISO-2 code → profile. Add a pack by importing it here.
_PROFILES: dict[str, CountryProfile] = {
    INDIA.code: INDIA,
}

_FALLBACK = INDIA

# Cache for active_profile() so per-voucher tax lookups don't re-read
# the licence file. Reset via set_active().
_active: CountryProfile | None = None


def get_profile(country_code: str | None) -> CountryProfile:
    """Look up a profile by ISO-2 code. Unknown / unbuilt countries
    fall back to India rather than raising — a licence for a country
    whose pack hasn't shipped yet still runs (as India) instead of
    crashing the app."""
    code = (country_code or "").strip().upper()
    return _PROFILES.get(code, _FALLBACK)


def available_country_codes() -> list[str]:
    """ISO-2 codes that have a real pack shipped in this build."""
    return sorted(_PROFILES.keys())


def active_profile() -> CountryProfile:
    """The profile selected by the active licence's country. Cached
    after first read; call set_active() to change it (tests, or after
    a licence re-validation changes the country)."""
    global _active
    if _active is None:
        try:
            from core.license_manager import LicenseManager
            _active = get_profile(LicenseManager().country)
        except Exception:
            _active = _FALLBACK
    return _active


def set_active(country_code: str | None) -> CountryProfile:
    """Force the active profile (tests, or re-selecting after the
    licence country changes). Returns the now-active profile."""
    global _active
    _active = get_profile(country_code)
    return _active


def reset_active() -> None:
    """Drop the cache so the next active_profile() re-reads the licence."""
    global _active
    _active = None
