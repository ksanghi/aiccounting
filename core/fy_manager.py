"""
Financial-year housekeeping.

The desktop's company seed (`main.py`) inserts a single FY row (2025-26) at
company creation. That's not enough — once we cross 2026-04-01 the user is
stuck posting into a year that has no `financial_years` row, which the
period-lock check needs.

`ensure_current_and_next()` runs at app startup (and from `MainWindow.__init__`
for each opened company) to:
  - insert a row for today's FY if missing, and
  - insert a row for next FY if today is within 60 days of current.end_date.

Idempotent — calling it twice is a no-op the second time.

FY convention here is April → March (Indian standard). The
`VoucherNumberer.get_fy()` helper is the single source of truth for the
string format, so we reuse it.
"""
from __future__ import annotations

from datetime import date, timedelta

from .voucher_engine import VoucherNumberer


def _fy_range(fy: str) -> tuple[str, str]:
    """Given '2025-26', return ('2025-04-01', '2026-03-31')."""
    start_year = int(fy.split("-")[0])
    return f"{start_year:04d}-04-01", f"{start_year + 1:04d}-03-31"


def _next_fy(fy: str) -> str:
    """Given '2025-26', return '2026-27'."""
    start_year = int(fy.split("-")[0]) + 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


def ensure_current_and_next(db, company_id: int) -> None:
    """
    Idempotently insert FY rows for `today` and (if within 60 days of
    current FY's end) for the next FY too. Safe to call on every app start.
    """
    today = date.today()
    current_fy = VoucherNumberer.get_fy(today.isoformat())
    start, end = _fy_range(current_fy)

    conn = db.connect()
    conn.execute(
        """INSERT OR IGNORE INTO financial_years
           (company_id, fy, start_date, end_date)
           VALUES (?,?,?,?)""",
        (company_id, current_fy, start, end),
    )

    end_date = date.fromisoformat(end)
    if (end_date - today) <= timedelta(days=60):
        nfy = _next_fy(current_fy)
        nstart, nend = _fy_range(nfy)
        conn.execute(
            """INSERT OR IGNORE INTO financial_years
               (company_id, fy, start_date, end_date)
               VALUES (?,?,?,?)""",
            (company_id, nfy, nstart, nend),
        )

    db.commit()
