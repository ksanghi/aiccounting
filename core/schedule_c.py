"""
US Schedule C (Form 1040) — expense categorisation + business mileage.

This is a REPORTING aid for sole proprietors (personal + small-store), not a
filing engine: we map expense ledgers to Schedule C lines and total them for the
year so the owner / their accountant can fill the form. We don't compute income
tax. (See `core/country/us.py`; `feedback-not-a-compliance-engine`.)

Two pieces:
  • SCHEDULE_C_LINES — the standard Part II expense lines. An expense ledger is
    tagged with a line's `code` via `ledgers.schedule_c_line`; the Schedule C
    report (`reports_engine.schedule_c`) sums expenses by that tag.
  • MileageLog — a trip log for the standard-mileage method. Business miles ×
    a configurable rate becomes the Car & Truck (line 9) deduction ON THE REPORT
    only; it is NOT posted to the books (the standard-mileage deduction is a tax
    figure, not a cash transaction). Actual car expenses (gas/repairs) are
    recorded as ordinary vouchers and tagged `car_truck` instead.
"""
from __future__ import annotations


# Part II expense lines (code, IRS line, label). `car_truck` (line 9) is where
# the standard-mileage deduction lands on the report.
SCHEDULE_C_LINES: list[dict] = [
    {"code": "advertising",        "line": "8",   "label": "Advertising"},
    {"code": "car_truck",          "line": "9",   "label": "Car and truck expenses"},
    {"code": "commissions",        "line": "10",  "label": "Commissions and fees"},
    {"code": "contract_labor",     "line": "11",  "label": "Contract labor (1099)"},
    {"code": "depreciation",       "line": "13",  "label": "Depreciation / sec 179"},
    {"code": "insurance",          "line": "15",  "label": "Insurance (other than health)"},
    {"code": "interest",           "line": "16",  "label": "Interest"},
    {"code": "legal_professional", "line": "17",  "label": "Legal & professional services"},
    {"code": "office",             "line": "18",  "label": "Office expense"},
    {"code": "rent_lease",         "line": "20",  "label": "Rent or lease"},
    {"code": "repairs",            "line": "21",  "label": "Repairs and maintenance"},
    {"code": "supplies",           "line": "22",  "label": "Supplies"},
    {"code": "taxes_licenses",     "line": "23",  "label": "Taxes and licenses"},
    {"code": "travel",             "line": "24a", "label": "Travel"},
    {"code": "meals",              "line": "24b", "label": "Deductible meals"},
    {"code": "utilities",          "line": "25",  "label": "Utilities"},
    {"code": "wages",              "line": "26",  "label": "Wages"},
    {"code": "other",              "line": "27a", "label": "Other expenses"},
]

_BY_CODE = {x["code"]: x for x in SCHEDULE_C_LINES}


def line_label(code: str | None) -> str:
    """Human label for a line code, or 'Uncategorised' for an untagged ledger."""
    if not code:
        return "Uncategorised"
    return _BY_CODE.get(code, {}).get("label", code)


def line_choices() -> list[tuple[str, str]]:
    """(code, 'line N — Label') pairs for a UI dropdown."""
    return [(x["code"], f"line {x['line']} — {x['label']}") for x in SCHEDULE_C_LINES]


# IRS standard mileage rate, $/mile. A DEFAULT the user can change at company
# setup — the rate changes yearly and the owner decides; we don't assert it as
# compliance. (2026 business rate placeholder; override per company.)
DEFAULT_MILEAGE_RATE = 0.70


class MileageLog:
    """Business-mileage trip log for the standard-mileage method."""

    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    def add(self, trip_date: str, miles: float,
            purpose: str = "", vehicle: str = "") -> int:
        cur = self.db.execute(
            """INSERT INTO mileage_log (company_id, trip_date, miles, purpose, vehicle)
               VALUES (?,?,?,?,?)""",
            (self.company_id, trip_date, float(miles), purpose, vehicle),
        )
        self.db.commit()
        return cur.lastrowid

    def entries(self, from_date: str, to_date: str) -> list[dict]:
        rows = self.db.execute(
            """SELECT id, trip_date, miles, purpose, vehicle
                 FROM mileage_log
                WHERE company_id=? AND trip_date BETWEEN ? AND ?
                ORDER BY trip_date, id""",
            (self.company_id, from_date, to_date),
        ).fetchall()
        return [dict(r) for r in rows]

    def total_miles(self, from_date: str, to_date: str) -> float:
        row = self.db.execute(
            """SELECT COALESCE(SUM(miles),0) AS m
                 FROM mileage_log
                WHERE company_id=? AND trip_date BETWEEN ? AND ?""",
            (self.company_id, from_date, to_date),
        ).fetchone()
        return round(row["m"] or 0.0, 1)

    def delete(self, entry_id: int) -> None:
        self.db.execute(
            "DELETE FROM mileage_log WHERE id=? AND company_id=?",
            (entry_id, self.company_id),
        )
        self.db.commit()
