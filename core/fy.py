"""
Financial-year arithmetic — pure, dependency-free.

A company's FY is defined by `companies.fy_start`, an 'MM-DD' string
(e.g. India '04-01', US/calendar '01-01', UK '04-06'). Every function
here takes that string explicitly so there is no hidden global; the
DB lookup lives in `core.fy_manager.company_fy_start`.

Backward-compatibility contract: for fy_start='04-01' (the schema
default and every existing Indian book) these helpers reproduce the
old hard-coded April-March behaviour byte-for-byte — same FY label
('2025-26'), same bounds ('2025-04-01'..'2026-03-31'). Only a company
that has set a different fy_start sees anything change.
"""
from __future__ import annotations

from datetime import date, timedelta


_DEFAULT = "04-01"


def _fy_start_md(fy_start: str) -> tuple[int, int]:
    """Parse 'MM-DD' into (month, day). Bad / empty input falls back to
    April 1. Day is capped at 28 so date math never overflows a short
    month — no real territory starts its FY after the 28th."""
    try:
        mm, dd = (fy_start or _DEFAULT).split("-")
        m, d = int(mm), int(dd)
        if 1 <= m <= 12 and 1 <= d <= 28:
            return m, d
    except (ValueError, AttributeError):
        pass
    return 4, 1


def fy_start_year(fy_start: str, d: date) -> int:
    """Calendar year in which the FY *containing* `d` begins."""
    m, dd = _fy_start_md(fy_start)
    return d.year if (d.month, d.day) >= (m, dd) else d.year - 1


def fy_label(fy_start: str, start_year: int) -> str:
    """Display string for the FY beginning in `start_year`.
    Calendar-year FYs (Jan start) read as 'YYYY'; straddling FYs read
    as 'YYYY-YY' — the format every existing voucher number uses."""
    m, _ = _fy_start_md(fy_start)
    if m == 1:
        return str(start_year)
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def fy_bounds(fy_start: str, start_year: int) -> tuple[str, str]:
    """(start_date, end_date) as ISO strings for the FY beginning in
    `start_year`. end_date is the day before the next FY starts."""
    m, dd = _fy_start_md(fy_start)
    start = date(start_year, m, dd)
    end = date(start_year + 1, m, dd) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def fy_for_date(fy_start: str, d: date) -> str:
    """Convenience: the FY label covering `d`."""
    return fy_label(fy_start, fy_start_year(fy_start, d))


def start_year_of_label(label: str) -> int:
    """Inverse of fy_label — pull the start year back out. Works for
    both 'YYYY' and 'YYYY-YY' because the year is always the leading
    token before the first dash."""
    return int(str(label).split("-")[0])
