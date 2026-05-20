"""
Financial-year housekeeping.

The desktop's company seed (`main.py`) inserts a single FY row at company
creation. That's not enough — once the calendar crosses into a new FY the
user is stuck posting into a year that has no `financial_years` row, which
the period-lock check needs.

`ensure_current_and_next()` runs at app startup (and from
`MainWindow.__init__` for each opened company) to:
  - insert a row for today's FY if missing, and
  - insert a row for next FY if today is within 60 days of current.end_date.

Idempotent — calling it twice is a no-op the second time.

FY boundaries are per-company: `companies.fy_start` ('MM-DD') drives them,
so an Indian book runs Apr-Mar, a US book Jan-Dec, etc. The pure
arithmetic lives in `core.fy`; this module only adds the DB lookup +
the financial_years upsert.
"""
from __future__ import annotations

from datetime import date, timedelta

from core.fy import fy_start_year, fy_label, fy_bounds


def company_fy_start(db, company_id: int) -> str:
    """Read `companies.fy_start` ('MM-DD'). Falls back to '04-01'
    (Indian April-March) if the row or column is empty."""
    row = db.connect().execute(
        "SELECT fy_start FROM companies WHERE id=?", (company_id,),
    ).fetchone()
    return (row["fy_start"] if row and row["fy_start"] else "04-01")


def ensure_current_and_next(db, company_id: int) -> None:
    """
    Idempotently insert FY rows for `today` and (if within 60 days of
    current FY's end) for the next FY too. FY boundaries follow the
    company's configured fy_start. Safe to call on every app start.
    """
    fy_start = company_fy_start(db, company_id)
    today = date.today()
    cur_year  = fy_start_year(fy_start, today)
    cur_label = fy_label(fy_start, cur_year)
    start, end = fy_bounds(fy_start, cur_year)

    conn = db.connect()
    conn.execute(
        """INSERT OR IGNORE INTO financial_years
           (company_id, fy, start_date, end_date)
           VALUES (?,?,?,?)""",
        (company_id, cur_label, start, end),
    )

    end_date = date.fromisoformat(end)
    if (end_date - today) <= timedelta(days=60):
        n_label = fy_label(fy_start, cur_year + 1)
        n_start, n_end = fy_bounds(fy_start, cur_year + 1)
        conn.execute(
            """INSERT OR IGNORE INTO financial_years
               (company_id, fy, start_date, end_date)
               VALUES (?,?,?,?)""",
            (company_id, n_label, n_start, n_end),
        )

    db.commit()
