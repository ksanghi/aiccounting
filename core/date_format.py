"""
Date display format — one user preference, applied everywhere.

Dates were hardcoded to ``dd-MMM-yyyy`` in the date-picker widgets while
table cells showed raw ISO (``yyyy-MM-dd``) — so the same screen could show
a date two different ways. This module is the single source of truth:

    from core.date_format import qt_format, format_iso

    edit.setDisplayFormat(qt_format())     # for SmartDateEdit / QDateEdit
    cell = format_iso(row["voucher_date"]) # for read-only table cells

The stored value is a Qt format string (so date-edit widgets can use it
directly); ``format_iso`` maps it to strftime for plain ISO strings coming
out of the DB. Pure-stdlib — no Qt import — so ``core`` stays GUI-free.
"""
from __future__ import annotations

from datetime import datetime

PREF_KEY = "date_display_format"
DEFAULT = "dd-MMM-yyyy"

# (qt_format, human label with a live example). Order = display order.
OPTIONS: list[tuple[str, str]] = [
    ("dd-MMM-yyyy", "13-Jun-2026   (day-month-year)"),
    ("dd/MM/yyyy",  "13/06/2026   (day/month/year)"),
    ("yyyy-MM-dd",  "2026-06-13   (ISO, year-month-day)"),
]

# Qt display format  →  Python strftime, for rendering ISO strings.
_TO_STRFTIME = {
    "dd-MMM-yyyy": "%d-%b-%Y",
    "dd/MM/yyyy":  "%d/%m/%Y",
    "yyyy-MM-dd":  "%Y-%m-%d",
}


def qt_format() -> str:
    """The current Qt display-format string (for date-edit widgets)."""
    try:
        from core.user_prefs import prefs
        val = prefs.get(PREF_KEY, DEFAULT)
        return val if val in _TO_STRFTIME else DEFAULT
    except Exception:
        return DEFAULT


def set_format(fmt: str) -> None:
    if fmt in _TO_STRFTIME:
        try:
            from core.user_prefs import prefs
            prefs.set(PREF_KEY, fmt)
        except Exception:
            pass


def format_iso(value) -> str:
    """Render an ISO date string ('yyyy-MM-dd', optionally with a time part)
    in the user's chosen format. Returns the input unchanged if it can't be
    parsed (so unexpected values never crash a table render)."""
    if not value:
        return ""
    s = str(value).strip()
    head = s.replace("T", " ").split(" ", 1)[0]   # date part only
    try:
        d = datetime.strptime(head, "%Y-%m-%d")
    except ValueError:
        return s
    return d.strftime(_TO_STRFTIME.get(qt_format(), _TO_STRFTIME[DEFAULT]))
