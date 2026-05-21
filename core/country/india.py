"""
India country pack (A13).

Encodes AccGenie's current behaviour exactly — India has always been
the implicit, hardcoded assumption. Routing through this profile is a
zero-change move; it just makes the assumption explicit and gives the
other packs (A13a US, A13b further) something to contrast against.

  • Tax system: India GST — CGST+SGST intra-state / IGST inter-state,
    driven by company-vs-party state codes (see core/voucher_engine.py).
    TDS sections layer on top.
  • Registration number: GSTIN.
  • Locale: lakh/crore digit grouping, ₹, DD-MM-YYYY dates.
  • Tax screens: the GST and TDS pages (feature keys "gst" / "tds").
"""
from __future__ import annotations

from core.country.base import CountryProfile


INDIA = CountryProfile(
    code="IN",
    name="India",
    locale_code="IN",
    currency_code="INR",
    currency_symbol="₹",
    date_format="%d-%m-%Y",
    tax_system="IN_GST",
    registration_label="GSTIN",
    uses_region_codes=True,
    tax_screens=("gst", "tds"),
)
