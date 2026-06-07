"""
Bill allocation dialog — Tally "Against Reference".

Opened from the voucher form for a RECEIPT / PAYMENT when the `bill_wise_refs`
feature is on and a party is selected. Lists the party's open bills and lets the
user split the voucher amount across them (oldest-first auto-fill); any
unallocated remainder posts on-account. Returns a list of allocation dicts that
the form attaches to VoucherDraft.allocations before engine.post().
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QPushButton, QDoubleSpinBox, QMessageBox,
)

from ui.theme import THEME
from core.bill_wise import BillWiseEngine


class BillAllocationDialog(QDialog):
    def __init__(self, db, company_id, party_id, party_name, amount, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.party_id = party_id
        self.amount = round(float(amount), 2)
        self._result: list = []
        self.setWindowTitle(f"Allocate against bills — {party_name}")
        self.resize(640, 440)
        self._bills = BillWiseEngine(db, company_id).open_bills(party_id)
        self._spins: list = []
        self._build()
        self._auto_fill()

    def _build(self):
        lay = QVBoxLayout(self)
        head = QLabel(
            f"Voucher amount: <b>₹{self.amount:,.2f}</b> — tick how much settles "
            f"each open bill (oldest first is auto-filled). Anything left over "
            f"posts on-account.")
        head.setWordWrap(True)
        lay.addWidget(head)

        if not self._bills:
            empty = QLabel("No open bills for this party — the amount will post "
                           "on-account.")
            empty.setStyleSheet(f"color:{THEME['text_secondary']}; padding:8px;")
            lay.addWidget(empty)

        self.table = QTableWidget(len(self._bills), 4)
        self.table.setHorizontalHeaderLabels(
            ["Bill No", "Bill Date", "Pending", "Allocate ₹"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        for i, b in enumerate(self._bills):
            self.table.setItem(i, 0, QTableWidgetItem(b["bill_number"] or "—"))
            self.table.setItem(i, 1, QTableWidgetItem(b["bill_date"]))
            pend = QTableWidgetItem(f"{b['pending_amount']:,.2f}")
            pend.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 2, pend)
            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            spin.setMaximum(max(0.0, round(b["pending_amount"], 2)))
            spin.setGroupSeparatorShown(True)
            spin.valueChanged.connect(self._update_remaining)
            self._spins.append(spin)
            self.table.setCellWidget(i, 3, spin)
        lay.addWidget(self.table, 1)

        self._remaining = QLabel("")
        self._remaining.setStyleSheet("font-size:12px; font-weight:bold;")
        lay.addWidget(self._remaining)

        brow = QHBoxLayout()
        auto = QPushButton("Auto-fill oldest"); auto.clicked.connect(self._auto_fill)
        clr  = QPushButton("Clear");            clr.clicked.connect(self._clear_all)
        brow.addWidget(auto); brow.addWidget(clr); brow.addStretch()
        cancel = QPushButton("Cancel");         cancel.clicked.connect(self.reject)
        ok = QPushButton("Apply");              ok.clicked.connect(self._apply)
        ok.setDefault(True)
        brow.addWidget(cancel); brow.addWidget(ok)
        lay.addLayout(brow)

    # ── helpers ──────────────────────────────────────────────────────────
    def _auto_fill(self):
        rem = self.amount
        for i, b in enumerate(self._bills):
            take = round(max(0.0, min(rem, b["pending_amount"])), 2)
            self._spins[i].setValue(take)
            rem = round(rem - take, 2)
        self._update_remaining()

    def _clear_all(self):
        for s in self._spins:
            s.setValue(0)
        self._update_remaining()

    def _allocated(self) -> float:
        return round(sum(s.value() for s in self._spins), 2)

    def _update_remaining(self):
        alloc = self._allocated()
        rem = round(self.amount - alloc, 2)
        if rem > 0:
            txt = f"Allocated ₹{alloc:,.2f}  ·  ₹{rem:,.2f} will post on-account"
            colour = THEME["text_secondary"]
        elif rem < 0:
            txt = f"Allocated ₹{alloc:,.2f}  ·  OVER by ₹{-rem:,.2f}"
            colour = THEME["danger"]
        else:
            txt = f"Allocated ₹{alloc:,.2f}  ·  fully allocated ✓"
            colour = THEME["success"]
        self._remaining.setText(txt)
        self._remaining.setStyleSheet(
            f"font-size:12px; font-weight:bold; color:{colour};")

    def _apply(self):
        alloc = self._allocated()
        if alloc - self.amount > 0.01:
            QMessageBox.warning(self, "Over-allocated",
                                "Allocated amount exceeds the voucher amount.")
            return
        result = []
        for i, b in enumerate(self._bills):
            v = round(self._spins[i].value(), 2)
            if v > 0:
                result.append({"bill_ref_id": b["id"], "amount": v,
                               "alloc_type": "AGAINST"})
        rem = round(self.amount - alloc, 2)
        if rem > 0.01:
            result.append({"bill_ref_id": None, "amount": rem,
                           "alloc_type": "ON_ACCOUNT"})
        self._result = result
        self.accept()

    def allocations(self) -> list:
        return self._result
