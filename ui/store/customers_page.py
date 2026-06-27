"""Store HQ — Customers: directory of named customers (each is a Sundry Debtor
ledger + a store_customers master row). F2 = new, F3 = edit."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QLineEdit, QDialog, QFormLayout, QDoubleSpinBox, QPlainTextEdit,
    QMessageBox, QAbstractItemView, QHeaderView,
)
from PySide6.QtGui import QKeySequence, QShortcut

from ui.theme import THEME
from ui.widgets import make_label
from ui.table_utils import make_sortable, apply_text_filter
from ui.store.inventory_page import _item
from ui.store.store_widgets import chip_btn


class CustomersPage(QWidget):
    TITLE = "Customers"

    def __init__(self, store_sales, store_engine, parent=None):
        super().__init__(parent)
        self.ss = store_sales
        self.se = store_engine
        self._ids = []
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(8)
        title = QLabel(self.TITLE); title.setObjectName("page_title"); root.addWidget(title)

        bar = QHBoxLayout(); bar.setSpacing(6)
        bar.addWidget(chip_btn("F2  New", "F2 — Add customer", self._add))
        bar.addWidget(chip_btn("F3  Edit", "F3 — Edit the selected customer", self._edit))
        self._search = QLineEdit(); self._search.setPlaceholderText("🔍 Filter customers…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda t: apply_text_filter(self._table, t))
        bar.addWidget(self._search, 1)
        bar.addWidget(chip_btn("↻", "Refresh", self.refresh))
        root.addLayout(bar)

        self._table = QTableWidget(); self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Name", "Contact", "Phone", "Email", "Balance"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.doubleClicked.connect(lambda _: self._edit())
        root.addWidget(self._table, 1)
        self._status = QLabel(""); self._status.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;")
        root.addWidget(self._status)

        QShortcut(QKeySequence("F2"), self).activated.connect(self._add)
        QShortcut(QKeySequence("F3"), self).activated.connect(self._edit)

    def refresh(self):
        rows = self.se.s.execute(
            "SELECT id, name, contact_person, phone, email, ledger_id "
            "FROM store_customers WHERE active=1 ORDER BY name").fetchall()
        self._ids = [r["id"] for r in rows]
        t = self._table; t.setSortingEnabled(False); t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            bal = self._balance(r["ledger_id"])
            t.setItem(i, 0, _item(r["name"]))
            t.setItem(i, 1, _item(r["contact_person"] or "—"))
            t.setItem(i, 2, _item(r["phone"] or "—"))
            t.setItem(i, 3, _item(r["email"] or "—"))
            t.setItem(i, 4, _item(f"{bal:.2f}", right=True))
        make_sortable(t)
        self._status.setText(f"{len(rows)} customers   ·   F2 new · F3 edit")

    def _balance(self, ledger_id):
        r = self.se.tree.db.execute(
            "SELECT COALESCE(SUM(dr_amount),0)-COALESCE(SUM(cr_amount),0) n "
            "FROM voucher_lines WHERE ledger_id=?", (ledger_id,)).fetchone()
        return round(r["n"] or 0.0, 2)

    def _selected(self):
        r = self._table.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    def _add(self):
        dlg = _CustomerDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.values()
            try:
                self.ss.add_customer(d.pop("name"), **d)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Add customer", str(e))

    def _edit(self):
        cid = self._selected()
        if not cid:
            QMessageBox.information(self, "Edit customer", "Select a customer, then press F3."); return
        row = self.se.s.execute("SELECT * FROM store_customers WHERE id=?", (cid,)).fetchone()
        dlg = _CustomerDialog(existing=row, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.ss.update_customer(cid, **dlg.values())
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Edit customer", str(e))


class _CustomerDialog(QDialog):
    def __init__(self, existing=None, parent=None):
        super().__init__(parent)
        self._edit = existing is not None
        self.setWindowTitle("Edit customer" if self._edit else "New customer")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self._name = QLineEdit(); self._contact = QLineEdit()
        self._phone = QLineEdit(); self._email = QLineEdit(); self._addr = QLineEdit()
        self._city = QLineEdit(); self._state = QLineEdit(); self._postal = QLineEdit()
        self._taxid = QLineEdit(); self._terms = QLineEdit()
        self._credit = QDoubleSpinBox(); self._credit.setRange(0, 1e9); self._credit.setDecimals(2)
        self._notes = QPlainTextEdit(); self._notes.setFixedHeight(48)
        form.addRow(make_label("Name", required=True), self._name)
        form.addRow(make_label("Contact person"), self._contact)
        form.addRow(make_label("Phone"), self._phone)
        form.addRow(make_label("Email"), self._email)
        form.addRow(make_label("Address"), self._addr)
        form.addRow(make_label("City"), self._city)
        form.addRow(make_label("State"), self._state)
        form.addRow(make_label("Postal code"), self._postal)
        form.addRow(make_label("Tax ID"), self._taxid)
        form.addRow(make_label("Payment terms"), self._terms)
        form.addRow(make_label("Credit limit"), self._credit)
        form.addRow(make_label("Notes"), self._notes)

        if self._edit:
            self._name.setText(existing["name"]); self._contact.setText(existing["contact_person"] or "")
            self._phone.setText(existing["phone"] or ""); self._email.setText(existing["email"] or "")
            self._addr.setText(existing["address"] or ""); self._city.setText(existing["city"] or "")
            self._state.setText(existing["state"] or ""); self._postal.setText(existing["postal_code"] or "")
            self._taxid.setText(existing["tax_id"] or ""); self._terms.setText(existing["terms"] or "")
            self._credit.setValue(existing["credit_limit"] or 0)
            self._notes.setPlainText(existing["notes"] or "")

        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject); row.addWidget(cancel)
        ok = QPushButton("Save" if self._edit else "Add"); ok.setObjectName("btn_primary")
        ok.clicked.connect(self._ok); row.addWidget(ok)
        form.addRow(row)

    def _ok(self):
        if not self._name.text().strip():
            QMessageBox.warning(self, "Customer", "Name is required."); return
        self.accept()

    def values(self):
        return {"name": self._name.text().strip(), "contact_person": self._contact.text().strip(),
                "phone": self._phone.text().strip(), "email": self._email.text().strip(),
                "address": self._addr.text().strip(), "city": self._city.text().strip(),
                "state": self._state.text().strip(), "postal_code": self._postal.text().strip(),
                "tax_id": self._taxid.text().strip(), "terms": self._terms.text().strip(),
                "credit_limit": self._credit.value(), "notes": self._notes.toPlainText().strip()}
