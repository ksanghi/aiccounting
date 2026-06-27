"""
CountryProfile — the shape of a country pack (A13).

A profile is pure declarative data: no logic, no DB access. The tax
*computation* still lives in core/voucher_engine.py; the profile only
says which tax system is in force and what it's called, so the engine
and the UI can branch on it.

Adding a country = create one module under core/country/ that builds a
CountryProfile and register it in core/country/__init__.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CountryProfile:
    # ── Identity ────────────────────────────────────────────────────
    code:  str            # ISO-2, e.g. "IN", "US"
    name:  str            # display name, e.g. "India"

    # ── Locale ──────────────────────────────────────────────────────
    # locale_code keys into core/i18n._LOCALE_FORMATS (number grouping
    # + currency symbol). date_format is a strftime pattern.
    locale_code:    str
    currency_code:  str            # ISO-4217, e.g. "INR"
    currency_symbol: str           # e.g. "₹"
    date_format:    str = "%d-%m-%Y"

    # ── Tax system ──────────────────────────────────────────────────
    # tax_system is a structural identifier the voucher engine branches
    # on. Today only "IN_GST" is implemented; "US_SALES_TAX" / "NONE"
    # arrive with their packs (A13a+).
    tax_system:     str = "NONE"
    # Label for the party/company tax-registration number field.
    registration_label: str = "Tax Registration No."
    # Does this country split tax by sub-national region (India: state
    # codes drive CGST+SGST vs IGST)? US sales tax is per-state too but
    # structurally different — its pack sets its own flag semantics.
    uses_region_codes:  bool = False

    # ── Screens ─────────────────────────────────────────────────────
    # Sidebar page keys that are country-specific and should only be
    # registered when this profile is active. India: GST + TDS pages.
    # A country with no such screens leaves this empty.
    tax_screens: tuple[str, ...] = field(default_factory=tuple)

    def has_tax(self) -> bool:
        return self.tax_system != "NONE"
