"""
Shared table utilities — sortable headers and a text filter that work
the same way on every QTableWidget in the app.

Two things ruin a naive `setSortingEnabled(True)`:

  - Amount cells like "₹1,234.56" sort as strings → ₹10 sorts before ₹2.
    Wrap them in `NumericTableItem(text, value=...)` so the header sorts
    by the numeric value behind the formatted string.

  - Calling `setItem` while sorting is enabled re-sorts after each call,
    which scrambles row indexes mid-populate. Use the `populating()`
    context manager (or call `setSortingEnabled(False)` yourself) before
    `setRowCount` / `setItem` and re-enable afterwards.
"""
from __future__ import annotations

from contextlib import contextmanager
from PySide6.QtCore    import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


_SORT_ROLE = Qt.ItemDataRole.UserRole + 100


class NumericTableItem(QTableWidgetItem):
    """Cell whose displayed text is decorative (₹, %, suffixes) but
    which should sort by an underlying numeric value."""

    def __init__(self, text: str, value: float | int | None):
        super().__init__(text)
        self.setData(_SORT_ROLE, float(value) if value is not None else 0.0)

    def __lt__(self, other):
        if isinstance(other, QTableWidgetItem):
            mine  = self.data(_SORT_ROLE)
            yours = other.data(_SORT_ROLE)
            if mine is not None and yours is not None:
                return mine < yours
        return super().__lt__(other)


def make_sortable(table: QTableWidget) -> None:
    """Turn on click-to-sort on a QTableWidget. Safe to call multiple
    times — idempotent."""
    table.setSortingEnabled(True)
    table.horizontalHeader().setSortIndicatorShown(True)
    table.horizontalHeader().setSectionsClickable(True)


@contextmanager
def populating(table: QTableWidget):
    """Disable sorting while bulk-setting rows, then restore. Without
    this, every `setItem` re-sorts and the row indexes you're writing
    into stop meaning what you think they mean."""
    was_on = table.isSortingEnabled()
    table.setSortingEnabled(False)
    try:
        yield
    finally:
        table.setSortingEnabled(was_on)


def apply_text_filter(table: QTableWidget, text: str) -> None:
    """Hide rows where no column contains the case-insensitive substring.
    Empty filter shows all rows. Matches the pattern already used by the
    bank reco unmatched-stmt filter."""
    needle = (text or "").strip().lower()
    for r in range(table.rowCount()):
        if not needle:
            table.setRowHidden(r, False)
            continue
        hit = False
        for c in range(table.columnCount()):
            item = table.item(r, c)
            if item and needle in (item.text() or "").lower():
                hit = True
                break
        table.setRowHidden(r, not hit)
