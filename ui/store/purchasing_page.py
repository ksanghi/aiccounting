"""Store HQ — Purchasing: suppliers, purchase orders, goods receipt (GRN).
Keyboard-first: F2 = new PO, F3 = receive selected PO, F6 = suppliers, F9 = direct GRN.
GRN posts stock IN + the purchase voucher to the books."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QLineEdit, QDialog, QFormLayout, QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit,
    QMessageBox, QAbstractItemView, QHeaderView,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QKeySequence, QShortcut

from ui.theme import THEME
from ui.widgets import make_label, SmartDateEdit
from ui.table_utils import make_sortable, apply_text_filter
from ui.store.inventory_page import _item
from ui.store.store_widgets import chip_btn
from core.date_format import qt_format


class PurchasingPage(QWidget):
    TITLE = "Purchasing"

    def __init__(self, store_engine, parent=None):
        super().__init__(parent)
        self.se = store_engine
        self._po_ids = []
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(8)
        title = QLabel(self.TITLE)
        title.setObjectName("page_title")
        root.addWidget(title)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(chip_btn("F2  New PO", "F2 — Create a purchase order", self._create_po))
        bar.addWidget(chip_btn("F3  Receive", "F3 — Receive (GRN) against the selected PO", self._receive_selected))
        bar.addWidget(chip_btn("F6  Suppliers", "F6 — Manage suppliers", self._suppliers_manager))
        bar.addWidget(chip_btn("F9  Direct GRN", "F9 — Receive goods without a PO", self._direct_grn))
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 Filter POs…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda t: apply_text_filter(self._table, t))
        bar.addWidget(self._search, 1)
        bar.addWidget(chip_btn("↻", "Refresh", self.refresh))
        root.addLayout(bar)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["PO #", "Supplier", "Date", "Status", "Subtotal"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.doubleClicked.connect(lambda _: self._receive_selected())
        root.addWidget(self._table, 1)
        self._status = QLabel("")
        self._status.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;")
        root.addWidget(self._status)

        QShortcut(QKeySequence("F2"), self).activated.connect(self._create_po)
        QShortcut(QKeySequence("F3"), self).activated.connect(self._receive_selected)
        QShortcut(QKeySequence("F6"), self).activated.connect(self._suppliers_manager)
        QShortcut(QKeySequence("F9"), self).activated.connect(self._direct_grn)

    # ── data ────────────────────────────────────────────────────────────────
    def _suppliers(self):
        return self.se.s.execute("SELECT id, name FROM store_suppliers WHERE active=1 ORDER BY name").fetchall()

    def _items(self):
        return self.se.s.execute(
            "SELECT id, sku, name, sale_price FROM store_items WHERE active=1 ORDER BY name").fetchall()

    def refresh(self):
        rows = self.se.s.execute(
            """SELECT po.id, po.po_no, s.name AS supplier, po.po_date, po.status, po.subtotal
                 FROM store_purchase_orders po
                 JOIN store_suppliers s ON s.id = po.supplier_id
                ORDER BY po.id DESC""").fetchall()
        t = self._table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        self._po_ids = []
        for i, r in enumerate(rows):
            self._po_ids.append(r["id"])
            t.setItem(i, 0, _item(r["po_no"]))
            t.setItem(i, 1, _item(r["supplier"]))
            t.setItem(i, 2, _item(r["po_date"]))
            t.setItem(i, 3, _item(r["status"]))
            t.setItem(i, 4, _item(f"{r['subtotal']:,.2f}", right=True))
        make_sortable(t)
        nsup = len(self._suppliers())
        self._status.setText(
            f"{len(rows)} purchase orders  ·  {nsup} suppliers   ·   F2 new PO · F3 receive · F6 suppliers · F9 direct GRN")

    def _selected_po(self):
        r = self._table.currentRow()
        if r < 0 or r >= len(self._po_ids):
            return None
        return self._po_ids[r]

    # ── suppliers ─────────────────────────────────────────────────────────────
    def _suppliers_manager(self):
        _SupplierManager(self.se, self).exec()
        self.refresh()

    # ── PO / GRN ────────────────────────────────────────────────────────────
    def _create_po(self):
        if not self._suppliers():
            QMessageBox.information(self, "Create PO", "Add a supplier first (F6)."); return
        if not self._items():
            QMessageBox.information(self, "Create PO", "Add items first (Inventory · F2)."); return
        dlg = _LineDialog("Create purchase order", self.se, mode="PO", parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.values()
            try:
                self.se.create_po(d["supplier_id"], d["lines"], po_date=d["date"],
                                  expected_date=d["expected_date"], terms=d["terms"], note=d["note"])
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Create PO", str(e))

    def _receive_selected(self):
        po_id = self._selected_po()
        if not po_id:
            QMessageBox.information(self, "Receive", "Select a PO, then press F3 (or use F9 for a direct GRN)."); return
        po = self.se.s.execute("SELECT * FROM store_purchase_orders WHERE id=?", (po_id,)).fetchone()
        if po["status"] == "RECEIVED":
            QMessageBox.information(self, "Receive", "This PO is already fully received."); return
        self._grn(po=po)

    def _direct_grn(self):
        if not self._suppliers():
            QMessageBox.information(self, "Receive", "Add a supplier first (F6)."); return
        if not self._items():
            QMessageBox.information(self, "Receive", "Add items first (Inventory · F2)."); return
        self._grn(po=None)

    def _grn(self, po):
        dlg = _LineDialog("Receive goods (GRN)", self.se, mode="GRN", po=po, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.values()
            try:
                res = self.se.receive_grn(
                    d["supplier_id"], d["lines"], grn_date=d["date"],
                    po_id=(po["id"] if po else None),
                    supplier_invoice_no=d["inv_no"], supplier_invoice_date=d["inv_date"],
                    due_date=d["due_date"], note=d["note"])
                QMessageBox.information(self, "GRN posted",
                    f"{res['grn_no']} received · total {res['total']:,.2f} · voucher {res['voucher_no']}")
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Receive", str(e))


# ── supplier master ────────────────────────────────────────────────────────────
class _SupplierManager(QDialog):
    """List of suppliers; F2 add, F3 edit. Honours the keyboard convention."""

    def __init__(self, store_engine, parent=None):
        super().__init__(parent)
        self.se = store_engine
        self._ids = []
        self.setWindowTitle("Suppliers")
        self.setMinimumSize(560, 420)
        root = QVBoxLayout(self)
        bar = QHBoxLayout(); bar.setSpacing(6)
        bar.addWidget(chip_btn("F2  New", "F2 — Add supplier", self._add))
        bar.addWidget(chip_btn("F3  Edit", "F3 — Edit selected supplier", self._edit))
        bar.addStretch()
        root.addLayout(bar)
        self._table = QTableWidget(); self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Name", "Contact", "Phone", "Terms"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.doubleClicked.connect(lambda _: self._edit())
        root.addWidget(self._table, 1)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        b = QHBoxLayout(); b.addStretch(); b.addWidget(close); root.addLayout(b)
        QShortcut(QKeySequence("F2"), self).activated.connect(self._add)
        QShortcut(QKeySequence("F3"), self).activated.connect(self._edit)
        self._reload()

    def _reload(self):
        rows = self.se.s.execute(
            "SELECT id, name, contact_person, phone, terms FROM store_suppliers WHERE active=1 ORDER BY name"
        ).fetchall()
        self._ids = [r["id"] for r in rows]
        t = self._table; t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            t.setItem(i, 0, _item(r["name"]))
            t.setItem(i, 1, _item(r["contact_person"] or "—"))
            t.setItem(i, 2, _item(r["phone"] or "—"))
            t.setItem(i, 3, _item(r["terms"] or "—"))

    def _selected(self):
        r = self._table.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    def _add(self):
        dlg = _SupplierDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.se.add_supplier(dlg.values().pop("name"), **dlg.values_no_name())
                self._reload()
            except Exception as e:
                QMessageBox.critical(self, "Add supplier", str(e))

    def _edit(self):
        sid = self._selected()
        if not sid:
            QMessageBox.information(self, "Edit supplier", "Select a supplier, then press F3."); return
        row = self.se.s.execute("SELECT * FROM store_suppliers WHERE id=?", (sid,)).fetchone()
        dlg = _SupplierDialog(existing=row, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.se.update_supplier(sid, **dlg.values_no_name(), name=dlg.values()["name"])
                self._reload()
            except Exception as e:
                QMessageBox.critical(self, "Edit supplier", str(e))


class _SupplierDialog(QDialog):
    def __init__(self, existing=None, parent=None):
        super().__init__(parent)
        self._edit = existing is not None
        self.setWindowTitle("Edit supplier" if self._edit else "New supplier")
        self.setMinimumWidth(440)
        form = QFormLayout(self)
        self._name = QLineEdit(); self._contact = QLineEdit()
        self._phone = QLineEdit(); self._alt = QLineEdit(); self._email = QLineEdit()
        self._web = QLineEdit(); self._addr = QLineEdit()
        self._city = QLineEdit(); self._state = QLineEdit(); self._postal = QLineEdit()
        self._country = QLineEdit("US"); self._taxid = QLineEdit(); self._terms = QLineEdit()
        self._lead = QSpinBox(); self._lead.setRange(0, 365)
        self._bank = QLineEdit(); self._acct = QLineEdit(); self._routing = QLineEdit()
        self._open = QDoubleSpinBox(); self._open.setRange(0, 1e9); self._open.setDecimals(2)
        self._notes = QPlainTextEdit(); self._notes.setFixedHeight(48)

        form.addRow(make_label("Name", required=True), self._name)
        form.addRow(make_label("Contact person"), self._contact)
        form.addRow(make_label("Phone"), self._phone)
        form.addRow(make_label("Alt phone"), self._alt)
        form.addRow(make_label("Email"), self._email)
        form.addRow(make_label("Website"), self._web)
        form.addRow(make_label("Address"), self._addr)
        form.addRow(make_label("City"), self._city)
        form.addRow(make_label("State"), self._state)
        form.addRow(make_label("Postal code"), self._postal)
        form.addRow(make_label("Country"), self._country)
        form.addRow(make_label("Tax ID / EIN"), self._taxid)
        form.addRow(make_label("Payment terms"), self._terms)
        form.addRow(make_label("Lead time (days)"), self._lead)
        form.addRow(make_label("Bank name"), self._bank)
        form.addRow(make_label("Bank account"), self._acct)
        form.addRow(make_label("Routing #"), self._routing)
        if not self._edit:
            form.addRow(make_label("Opening balance (we owe)"), self._open)
        form.addRow(make_label("Notes"), self._notes)

        if self._edit:
            self._name.setText(existing["name"]); self._contact.setText(existing["contact_person"] or "")
            self._phone.setText(existing["phone"] or ""); self._alt.setText(existing["alt_phone"] or "")
            self._email.setText(existing["email"] or ""); self._web.setText(existing["website"] or "")
            self._addr.setText(existing["address"] or ""); self._city.setText(existing["city"] or "")
            self._state.setText(existing["state"] or ""); self._postal.setText(existing["postal_code"] or "")
            self._country.setText(existing["country"] or "US"); self._taxid.setText(existing["tax_id"] or "")
            self._terms.setText(existing["terms"] or ""); self._lead.setValue(existing["lead_time_days"] or 0)
            self._bank.setText(existing["bank_name"] or ""); self._acct.setText(existing["bank_account"] or "")
            self._routing.setText(existing["bank_routing"] or "")
            self._notes.setPlainText(existing["notes"] or "")

        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject); row.addWidget(cancel)
        ok = QPushButton("Save" if self._edit else "Add"); ok.setObjectName("btn_primary")
        ok.clicked.connect(self._ok); row.addWidget(ok)
        form.addRow(row)

    def _ok(self):
        if not self._name.text().strip():
            QMessageBox.warning(self, "Supplier", "Name is required."); return
        self.accept()

    def values(self):
        return {"name": self._name.text().strip(), **self.values_no_name()}

    def values_no_name(self):
        d = {"contact_person": self._contact.text().strip(), "phone": self._phone.text().strip(),
             "alt_phone": self._alt.text().strip(), "email": self._email.text().strip(),
             "website": self._web.text().strip(), "address": self._addr.text().strip(),
             "city": self._city.text().strip(), "state": self._state.text().strip(),
             "postal_code": self._postal.text().strip(), "country": self._country.text().strip() or "US",
             "tax_id": self._taxid.text().strip(), "terms": self._terms.text().strip(),
             "lead_time_days": self._lead.value(), "bank_name": self._bank.text().strip(),
             "bank_account": self._acct.text().strip(), "bank_routing": self._routing.text().strip(),
             "notes": self._notes.toPlainText().strip()}
        if not self._edit:
            d["opening_balance"] = self._open.value()
        return d


# ── PO / GRN line builder ────────────────────────────────────────────────────
class _LineDialog(QDialog):
    """Pick a supplier + build item/qty/rate lines. mode='PO' or 'GRN'.
    A PO may be passed for a GRN to lock the supplier and prefill lines."""

    def __init__(self, title, store_engine, *, mode="PO", po=None, parent=None):
        super().__init__(parent)
        self.se = store_engine
        self.mode = mode
        self._po = po
        self._lines = []
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)

        top = QFormLayout()
        sup_row = QHBoxLayout()
        self._sup = QComboBox()
        self._reload_suppliers()
        sup_row.addWidget(self._sup, 1)
        sup_row.addWidget(chip_btn("F2", "F2 — Add a supplier on the fly", self._add_supplier))
        top.addRow(make_label("Supplier", required=True), sup_row)
        self._date = SmartDateEdit(QDate.currentDate()); self._date.setDisplayFormat(qt_format())
        top.addRow(make_label("Date"), self._date)

        if mode == "PO":
            self._expected = SmartDateEdit(QDate.currentDate().addDays(7)); self._expected.setDisplayFormat(qt_format())
            self._terms = QLineEdit()
            top.addRow(make_label("Expected date"), self._expected)
            top.addRow(make_label("Terms"), self._terms)
        else:  # GRN
            self._inv_no = QLineEdit()
            self._inv_date = SmartDateEdit(QDate.currentDate()); self._inv_date.setDisplayFormat(qt_format())
            self._due = SmartDateEdit(QDate.currentDate().addDays(30)); self._due.setDisplayFormat(qt_format())
            top.addRow(make_label("Supplier invoice #"), self._inv_no)
            top.addRow(make_label("Invoice date"), self._inv_date)
            top.addRow(make_label("Due date"), self._due)
        self._note = QLineEdit()
        top.addRow(make_label("Note"), self._note)
        root.addLayout(top)

        addrow = QHBoxLayout()
        self._item = QComboBox()
        self._reload_items()
        self._qty = QDoubleSpinBox(); self._qty.setRange(0, 1e6); self._qty.setValue(1)
        self._rate = QDoubleSpinBox(); self._rate.setRange(0, 1e7); self._rate.setDecimals(2)
        addrow.addWidget(self._item, 2)
        addrow.addWidget(make_label("Qty")); addrow.addWidget(self._qty)
        addrow.addWidget(make_label("Rate")); addrow.addWidget(self._rate)
        addrow.addWidget(chip_btn("＋ line", "Add line", self._add_line))
        root.addLayout(addrow)

        self._tbl = QTableWidget(); self._tbl.setColumnCount(4)
        self._tbl.setHorizontalHeaderLabels(["Item", "Qty", "Rate", "Amount"])
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tbl.verticalHeader().setVisible(False)
        root.addWidget(self._tbl, 1)
        self._total = QLabel("Total: 0.00")
        root.addWidget(self._total)

        btn = QHBoxLayout(); btn.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject); btn.addWidget(cancel)
        ok = QPushButton("Save"); ok.setObjectName("btn_primary"); ok.clicked.connect(self._ok); btn.addWidget(ok)
        root.addLayout(btn)

        # GRN against a PO → lock supplier + prefill remaining lines
        if mode == "GRN" and po is not None:
            i = self._sup.findData(po["supplier_id"])
            if i >= 0:
                self._sup.setCurrentIndex(i)
            self._sup.setEnabled(False)
            self._prefill_from_po(po["id"])

    def _reload_suppliers(self):
        cur = self._sup.currentData() if self._sup.count() else None
        self._sup.clear()
        for r in self.se.s.execute(
                "SELECT id, name FROM store_suppliers WHERE active=1 ORDER BY name").fetchall():
            self._sup.addItem(r["name"], r["id"])
        if cur is not None:
            i = self._sup.findData(cur)
            if i >= 0:
                self._sup.setCurrentIndex(i)

    def _reload_items(self):
        self._item.clear()
        self._item_labels = {}
        for r in self.se.s.execute(
                "SELECT id, sku, name FROM store_items WHERE active=1 ORDER BY name").fetchall():
            label = f"{r['sku']} — {r['name']}"
            self._item.addItem(label, r["id"])
            self._item_labels[r["id"]] = label

    def _add_supplier(self):
        dlg = _SupplierDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                sid = self.se.add_supplier(dlg.values()["name"], **dlg.values_no_name())
                self._reload_suppliers()
                i = self._sup.findData(sid)
                if i >= 0:
                    self._sup.setCurrentIndex(i)
            except Exception as e:
                QMessageBox.critical(self, "Add supplier", str(e))

    def _prefill_from_po(self, po_id):
        rows = self.se.s.execute(
            "SELECT item_id, qty, received_qty, rate FROM store_po_lines WHERE po_id=?", (po_id,)).fetchall()
        for r in rows:
            remaining = (r["qty"] or 0) - (r["received_qty"] or 0)
            if remaining > 1e-9:
                self._lines.append((r["item_id"], remaining, r["rate"] or 0.0,
                                    self._item_labels.get(r["item_id"], str(r["item_id"]))))
        self._render()

    def _add_line(self):
        item_id = self._item.currentData()
        qty = self._qty.value(); rate = self._rate.value()
        if qty <= 0:
            return
        self._lines.append((item_id, qty, rate, self._item.currentText()))
        self._render()

    def _render(self):
        self._tbl.setRowCount(len(self._lines))
        total = 0.0
        for i, (iid, q, r, label) in enumerate(self._lines):
            amt = q * r
            self._tbl.setItem(i, 0, _item(label))
            self._tbl.setItem(i, 1, _item(f"{q:g}", right=True))
            self._tbl.setItem(i, 2, _item(f"{r:.2f}", right=True))
            self._tbl.setItem(i, 3, _item(f"{amt:.2f}", right=True))
            total += amt
        self._total.setText(f"Total: {total:,.2f}")

    def _ok(self):
        if not self._lines:
            QMessageBox.warning(self, "Lines", "Add at least one line."); return
        self.accept()

    def values(self):
        d = {"supplier_id": self._sup.currentData(),
             "date": self._date.date().toString("yyyy-MM-dd"),
             "lines": [(iid, q, r) for iid, q, r, _ in self._lines],
             "note": self._note.text().strip()}
        if self.mode == "PO":
            d["expected_date"] = self._expected.date().toString("yyyy-MM-dd")
            d["terms"] = self._terms.text().strip()
        else:
            d["inv_no"] = self._inv_no.text().strip()
            d["inv_date"] = self._inv_date.date().toString("yyyy-MM-dd")
            d["due_date"] = self._due.date().toString("yyyy-MM-dd")
        return d
