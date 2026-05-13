"""
Period Locks page — manage financial-year closure and ad-hoc date-range locks.

Two cards:
  1. Financial Years — lists FY rows from `financial_years`, with Close /
     Reopen per row. Closing a FY blocks post/edit/cancel for any date in
     its range (enforced in core/voucher_engine.py).
  2. Date-range locks — lists `period_locks` rows. Add new lock via dialog
     asking from/to/reason. Per-row Delete to remove a lock.

Both actions append to `audit_log` (no roles right now, but the trail
matters when the customer asks who closed what).
"""
from __future__ import annotations

import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QFormLayout, QLineEdit, QMessageBox, QAbstractItemView,
)
from PySide6.QtCore import Qt, QDate

from ui.theme import THEME
from ui.widgets import make_label, SmartDateEdit


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        font-size: 13px;
        font-weight: bold;
        color: {THEME['text_primary']};
        padding: 4px 0px 6px 0px;
    """)
    return lbl


class _AddLockDialog(QDialog):
    """Modal: pick from-date, to-date, reason → returns (from, to, reason)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add period lock")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        hint = QLabel(
            "Lock a date range so vouchers in it cannot be posted, edited, "
            "or cancelled. Bank reconciliation clearing is still allowed."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {THEME['text_secondary']}; font-size: 11px;")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(8)

        today = QDate.currentDate()
        self._from_edit = SmartDateEdit(QDate(today.year(), today.month(), 1))
        self._from_edit.setDisplayFormat("dd-MMM-yyyy")
        self._from_edit.setFixedHeight(34)
        form.addRow(make_label("Lock from", required=True), self._from_edit)

        self._to_edit = SmartDateEdit(today)
        self._to_edit.setDisplayFormat("dd-MMM-yyyy")
        self._to_edit.setFixedHeight(34)
        form.addRow(make_label("Lock to", required=True), self._to_edit)

        self._reason_edit = QLineEdit()
        self._reason_edit.setPlaceholderText("e.g. GST return filed; April month closed")
        self._reason_edit.setFixedHeight(34)
        form.addRow(make_label("Reason"), self._reason_edit)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(34)
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Add lock")
        ok_btn.setObjectName("btn_primary")
        ok_btn.setFixedHeight(34)
        ok_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _on_accept(self):
        lo = self._from_edit.date().toString("yyyy-MM-dd")
        hi = self._to_edit.date().toString("yyyy-MM-dd")
        if hi < lo:
            QMessageBox.warning(self, "Bad range",
                                "'Lock to' must be on or after 'Lock from'.")
            return
        self._result = (lo, hi, self._reason_edit.text().strip())
        self.accept()

    def values(self) -> tuple[str, str, str]:
        return self._result


class PeriodLocksPage(QWidget):
    """Settings → Period Locks page."""

    def __init__(self, db, company_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self._build_ui()
        self.refresh()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 0, 24, 24)
        outer.setSpacing(0)

        title = QLabel("Period Locks")
        title.setObjectName("page_title")
        outer.addWidget(title)

        sub = QLabel(
            "Close financial years and lock date ranges to prevent further "
            "changes. Anyone with company access can close or unlock a "
            "period — every action is recorded in the audit log."
        )
        sub.setObjectName("page_subtitle")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        body = QVBoxLayout()
        body.setSpacing(16)

        # ── Card 1: Financial Years ──
        body.addWidget(_section_label("Financial Years"))
        fy_card = QFrame()
        fy_card.setObjectName("card")
        fy_card.setStyleSheet(f"""
            QFrame#card {{
                background: {THEME['bg_card']};
                border: 1px solid {THEME['border']};
                border-radius: 10px;
            }}
        """)
        fyc = QVBoxLayout(fy_card)
        fyc.setContentsMargins(16, 14, 16, 14)
        fyc.setSpacing(8)

        self._fy_table = QTableWidget(0, 4)
        self._fy_table.setHorizontalHeaderLabels(
            ["FY", "Start", "End", "Status"]
        )
        self._fy_table.verticalHeader().setVisible(False)
        self._fy_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._fy_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        h = self._fy_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._fy_table.setMinimumHeight(120)
        fyc.addWidget(self._fy_table)
        body.addWidget(fy_card)

        # ── Card 2: Date-range locks ──
        head_row = QHBoxLayout()
        head_row.addWidget(_section_label("Date-range locks"))
        head_row.addStretch()
        add_btn = QPushButton("+ Add lock")
        add_btn.setObjectName("btn_primary")
        add_btn.setFixedHeight(34)
        add_btn.clicked.connect(self._add_lock)
        head_row.addWidget(add_btn)
        body.addLayout(head_row)

        lk_card = QFrame()
        lk_card.setObjectName("card")
        lk_card.setStyleSheet(f"""
            QFrame#card {{
                background: {THEME['bg_card']};
                border: 1px solid {THEME['border']};
                border-radius: 10px;
            }}
        """)
        lkc = QVBoxLayout(lk_card)
        lkc.setContentsMargins(16, 14, 16, 14)
        lkc.setSpacing(8)

        self._lk_table = QTableWidget(0, 5)
        self._lk_table.setHorizontalHeaderLabels(
            ["From", "To", "Reason", "Locked at", ""]
        )
        self._lk_table.verticalHeader().setVisible(False)
        self._lk_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._lk_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        h2 = self._lk_table.horizontalHeader()
        h2.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h2.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h2.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h2.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h2.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._lk_table.setMinimumHeight(140)
        lkc.addWidget(self._lk_table)
        body.addWidget(lk_card)

        body.addStretch()
        outer.addLayout(body, 1)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self):
        self._fill_fy_table()
        self._fill_lk_table()

    def _fill_fy_table(self):
        rows = self.db.execute(
            """SELECT id, fy, start_date, end_date, is_closed
                 FROM financial_years
                WHERE company_id=?
                ORDER BY start_date""",
            (self.company_id,),
        ).fetchall()
        self._fy_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self._fy_table.setItem(r, 0, QTableWidgetItem(row["fy"]))
            self._fy_table.setItem(r, 1, QTableWidgetItem(row["start_date"]))
            self._fy_table.setItem(r, 2, QTableWidgetItem(row["end_date"]))

            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(6, 2, 6, 2)
            cl.setSpacing(8)

            status_lbl = QLabel("Closed" if row["is_closed"] else "Open")
            status_lbl.setStyleSheet(
                f"color: {THEME['danger'] if row['is_closed'] else THEME['success']};"
                f"font-size: 11px; font-weight: bold;"
            )
            cl.addWidget(status_lbl)
            cl.addStretch()

            btn = QPushButton("Reopen" if row["is_closed"] else "Close")
            btn.setFixedHeight(28)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {THEME['accent']};
                    border: 1px solid {THEME['accent']};
                    border-radius: 6px;
                    padding: 2px 12px;
                    font-size: 11px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background: {THEME['accent']}; color: white;
                }}
            """)
            fy_id = row["id"]
            fy_str = row["fy"]
            was_closed = bool(row["is_closed"])
            btn.clicked.connect(
                lambda _, i=fy_id, f=fy_str, c=was_closed:
                    self._toggle_fy(i, f, c)
            )
            cl.addWidget(btn)
            self._fy_table.setCellWidget(r, 3, cell)

    def _fill_lk_table(self):
        rows = self.db.execute(
            """SELECT id, lock_from, lock_to, reason, locked_at
                 FROM period_locks
                WHERE company_id=?
                ORDER BY lock_from""",
            (self.company_id,),
        ).fetchall()
        self._lk_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self._lk_table.setItem(r, 0, QTableWidgetItem(row["lock_from"]))
            self._lk_table.setItem(r, 1, QTableWidgetItem(row["lock_to"]))
            self._lk_table.setItem(r, 2, QTableWidgetItem(row["reason"] or ""))
            self._lk_table.setItem(r, 3, QTableWidgetItem(row["locked_at"][:16]))

            del_btn = QPushButton("Delete")
            del_btn.setFixedHeight(28)
            del_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {THEME['danger']};
                    border: 1px solid {THEME['danger']};
                    border-radius: 6px;
                    padding: 2px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background: {THEME['danger']}; color: white;
                }}
            """)
            lk_id = row["id"]
            lf, lt = row["lock_from"], row["lock_to"]
            del_btn.clicked.connect(
                lambda _, i=lk_id, f=lf, t=lt: self._delete_lock(i, f, t)
            )
            self._lk_table.setCellWidget(r, 4, del_btn)

    # ── Mutations (each audit-logged) ─────────────────────────────────────────

    def _toggle_fy(self, fy_id: int, fy: str, was_closed: bool):
        action = "REOPEN_FY" if was_closed else "CLOSE_FY"
        verb = "reopen" if was_closed else "close"
        reply = QMessageBox.question(
            self, f"{verb.capitalize()} FY {fy}?",
            (f"Reopen FY {fy} so users can post / edit / cancel "
             f"vouchers in that year again?"
             if was_closed else
             f"Close FY {fy}? All post / edit / cancel operations "
             f"for dates in this FY will be blocked until you reopen it."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        new_val = 0 if was_closed else 1
        with self.db:
            self.db.execute(
                "UPDATE financial_years SET is_closed=? WHERE id=?",
                (new_val, fy_id),
            )
            self.db.execute(
                """INSERT INTO audit_log
                   (company_id, user_id, action, table_name, record_id, new_data)
                   VALUES (?,?,?,?,?,?)""",
                (
                    self.company_id, None, action,
                    "financial_years", fy_id,
                    json.dumps({"fy": fy, "is_closed": new_val}),
                ),
            )
        self.refresh()

    def _add_lock(self):
        dlg = _AddLockDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        lo, hi, reason = dlg.values()
        with self.db:
            cur = self.db.execute(
                """INSERT INTO period_locks
                   (company_id, lock_from, lock_to, reason)
                   VALUES (?,?,?,?)""",
                (self.company_id, lo, hi, reason or None),
            )
            self.db.execute(
                """INSERT INTO audit_log
                   (company_id, user_id, action, table_name, record_id, new_data)
                   VALUES (?,?,?,?,?,?)""",
                (
                    self.company_id, None, "ADD_PERIOD_LOCK",
                    "period_locks", cur.lastrowid,
                    json.dumps({"from": lo, "to": hi, "reason": reason}),
                ),
            )
        self.refresh()

    def _delete_lock(self, lk_id: int, lo: str, hi: str):
        reply = QMessageBox.question(
            self, "Remove lock?",
            f"Remove the lock for {lo} → {hi}? Vouchers in that range "
            f"can be posted / edited / cancelled again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        with self.db:
            self.db.execute(
                "DELETE FROM period_locks WHERE id=?",
                (lk_id,),
            )
            self.db.execute(
                """INSERT INTO audit_log
                   (company_id, user_id, action, table_name, record_id, old_data)
                   VALUES (?,?,?,?,?,?)""",
                (
                    self.company_id, None, "DELETE_PERIOD_LOCK",
                    "period_locks", lk_id,
                    json.dumps({"from": lo, "to": hi}),
                ),
            )
        self.refresh()
