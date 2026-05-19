"""
Territory-aware number / currency formatting.

The whole app used to hardcode Indian grouping — ``f"₹{x:,.2f}"`` —
which on Python's default ``,`` grouping renders 1,000-groups
(``₹1,234,567.89``). That's wrong for India (which uses lakh/crore
grouping ``₹12,34,567.89``) and meaningless for non-India markets.

This module wraps that logic behind two calls:

    format_amount(value)              -> "12,34,567.89"   (IN default)
    format_currency(value)            -> "₹ 12,34,567.89"

Both consult the user pref ``display_locale`` (ISO-2 country code,
defaults to ``IN``). When the operator opens AccGenie for a non-India
company they can flip the pref via ``Settings → Locale`` (UI to be
added) and every report re-formats on next refresh.

Adding a new locale: add an entry to ``_LOCALE_FORMATS`` below.
"""
from __future__ import annotations

from typing import Optional

from core.user_prefs import prefs


# Per-locale formatting rules. Each tuple is:
#   (group_widths, group_sep, decimal_sep, currency_symbol)
#
# group_widths: tuple of digit-group widths reading right-to-left.
#   (3,)    → repeat groups of 3   (US/EU/most): 1,234,567
#   (3, 2)  → first group of 3, then 2s thereafter (India): 12,34,567
#
# Currency symbol is informational here — most live code looks the
# symbol up via core/pricing.py (per-country). This is the fallback
# when no pricing row is loaded.
_LOCALE_FORMATS: dict[str, tuple] = {
    "IN":  ((3, 2), ",", ".", "₹"),
    "US":  ((3,),   ",", ".", "$"),
    "GB":  ((3,),   ",", ".", "£"),
    "EU":  ((3,),   ".", ",", "€"),    # German/French style
    "SG":  ((3,),   ",", ".", "S$"),
    "AE":  ((3,),   ",", ".", "د.إ"),
}

_DEFAULT_LOCALE = "IN"


def display_locale() -> str:
    """Active locale code. Reads `display_locale` pref; falls back to IN."""
    code = (prefs.get("display_locale") or _DEFAULT_LOCALE).strip().upper()
    return code if code in _LOCALE_FORMATS else _DEFAULT_LOCALE


def currency_symbol(locale: Optional[str] = None) -> str:
    fmt = _LOCALE_FORMATS.get((locale or display_locale()).upper(),
                              _LOCALE_FORMATS[_DEFAULT_LOCALE])
    return fmt[3]


def format_amount(value: float, locale: Optional[str] = None) -> str:
    """Format `value` to 2 decimals with locale-appropriate digit
    grouping. No currency symbol, no leading/trailing spaces. Negative
    values render with a leading minus sign."""
    code = (locale or display_locale()).upper()
    group_widths, group_sep, decimal_sep, _ = _LOCALE_FORMATS.get(
        code, _LOCALE_FORMATS[_DEFAULT_LOCALE]
    )
    neg = value < 0
    s = f"{abs(float(value)):.2f}"
    int_part, _, frac_part = s.partition(".")

    # Walk right-to-left, slicing off groups according to group_widths.
    # The last entry in group_widths repeats indefinitely once consumed
    # — that's how Indian grouping (3,2) keeps adding 2s past the first
    # comma: 1,23,45,67,890.
    groups: list[str] = []
    rest = int_part
    idx = 0
    while rest:
        w = group_widths[min(idx, len(group_widths) - 1)]
        groups.append(rest[-w:])
        rest = rest[:-w]
        idx += 1
    grouped = group_sep.join(reversed(groups))
    out = f"{grouped}{decimal_sep}{frac_part}"
    return f"-{out}" if neg else out


def format_currency(value: float, locale: Optional[str] = None,
                     symbol: Optional[str] = None) -> str:
    """Like format_amount but prefixed with the currency symbol +
    one space. `symbol` overrides the locale default (e.g. when a
    pricing row already knows the right symbol per country)."""
    code = (locale or display_locale()).upper()
    sym = symbol if symbol is not None else currency_symbol(code)
    return f"{sym} {format_amount(value, code)}"
