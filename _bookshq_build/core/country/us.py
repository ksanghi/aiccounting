"""
US country pack (A13a) — activates "Books HQ", the US regional breakout of the
same super-AHQ build. Selected when a licence's country_code == "US".

Scope (decided with the user):
  • Tax system: US SALES/USE TAX — a flat rate the store configures at company
    setup and applies on invoices (NO nexus / per-state auto-computation /
    multi-branch — target is personal + small-store accounting). Input/use tax
    on purchases is recorded (credit where applicable). The voucher engine
    branches on tax_system="US_SALES_TAX" (vs India's IN_GST state-code split).
  • Income tax: NOT computed (same as India — we record, we don't file).
  • 1099 contractor tracking: the TDS engine in report-only mode (track + report
    payments to flagged contractors; NO withholding). US-specific screens.
  • Payroll: OUT of scope.
  • Registration number: EIN.
  • Locale: USD, $, MM/DD/YYYY, no sub-national tax split.
"""
from __future__ import annotations

from core.country.base import CountryProfile

US = CountryProfile(
    code="US",
    name="United States",
    locale_code="US",
    currency_code="USD",
    currency_symbol="$",
    date_format="%m/%d/%Y",
    tax_system="US_SALES_TAX",
    registration_label="EIN",
    uses_region_codes=False,        # single configured rate — no state-code split
    tax_screens=("schedule_c", "1099"),   # Books HQ US tax screens (A13 gate)
)
