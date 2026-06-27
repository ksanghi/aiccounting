"""Store HQ — Counter (POS-light): ring up a sale → record_counter_sale; close
the day → one daily invoice; plus a named-customer invoice.
Keyboard-first: F2 = new invoice, F4 = close day, Enter on price = add to cart."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QComboBox, QDoubleSpinBox, QDialog, QFormLayout, QLineEdit, QMessageBox,
    QAbstractItemView, QHeaderView,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QKeySequence, QShortcut

from ui.theme import THEME
from ui.widgets import make_label
from ui.store.inventory_page import _item
from ui.store.store_widgets import chip_btn


class POSPage(QWidget):
    TITLE = "Counter (POS)"

    def __init__(self, store_sales, store_engine, parent=None):
        super().__init__(parent)
        self.ss = store_sales
        self.se = store_engine
        self._cart = []      # (item_id, qty, price, label)
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel(self.TITLE); title.setObjectName("page_title"); head.addWidget(title)
        head.addStretch()
        head.addWidget(chip_btn("F2  New invoice", "F2 — Named-customer invoice", self._new_invoice))
        head.addWidget(chip_btn("F4  Close day", "F4 — Post the day's counter sales", self._close_day))
        root.addLayout(head)

        # add-to-cart row
        add = QHBoxLayout()
        self._item = QComboBox(); self._item.currentIndexChanged.connect(self._fill_price)
        self._qty = QDoubleSpinBox(); self._qty.setRange(0, 1e6); self._qty.setValue(1)
        self._price = QDoubleSpinBox(); self._price.setRange(0, 1e7); self._price.setDecimals(2)
        self._price.editingFinished.connect(lambda: None)
        add.addWidget(self._item, 2)
        add.addWidget(make_label("Qty")); add.addWidget(self._qty)
        add.addWidget(make_label("Price")); add.addWidget(self._price)
        add.addWidget(chip_btn("＋ add", "Add to cart (Enter)", self._add_to_cart))
        root.addLayout(add)

        self._cart_tbl = QTableWidget(); self._cart_tbl.setColumnCount(4)
        self._cart_tbl.setHorizontalHeaderLabels(["Item", "Qty", "Price", "Amount"])
        self._cart_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._cart_tbl.verticalHeader().setVisible(False)
        self._cart_tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        root.addWidget(self._cart_tbl, 1)

        pay = QHBoxLayout()
        self._totals = QLabel("Subtotal 0.00   Tax 0.00   Total 0.00")
        self._totals.setStyleSheet("font-weight:bold;")
        pay.addWidget(self._totals); pay.addStretch()
        pay.addWidget(make_label("Tender"))
        self._tender = QComboBox(); self._tender.addItems(["CASH", "CARD", "UPI"])
        pay.addWidget(self._tender)
        pay.addWidget(chip_btn("Clear", "Empty the cart", self._clear_cart))
        done = QPushButton("✔  Complete sale"); done.setObjectName("btn_primary")
        done.clicked.connect(self._complete); pay.addWidget(done)
        root.addLayout(pay)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;")
        root.addWidget(self._status)

        QShortcut(QKeySequence("F2"), self).activated.connect(self._new_invoice)
        QShortcut(QKeySequence("F4"), self).activated.connect(self._close_day)
        QShortcut(QKeySequence(Qt.Key.Key_Return), self).activated.connect(self._add_to_cart)
        QShortcut(QKeySequence(Qt.Key.Key_Enter), self).activated.connect(self._add_to_cart)

    # ── helpers ───────────────────────────────────────────────────────────────
    def _load_items(self):
        self._items = self.se.s.execute(
            "SELECT id, sku, name, sale_price FROM store_items WHERE active=1 ORDER BY name").fetchall()
        self._item.clear()
        for r in self._items:
            self._item.addItem(f"{r['sku']} — {r['name']}", (r["id"], r["sale_price"]))

    def _fill_price(self):
        d = self._item.currentData()
        if d:
            self._price.setValue(float(d[1] or 0))

    def refresh(self):
        self._load_items()
        self._render_cart()
        recv = self.ss.counter_receivable_balance()
        self._status.setText(
            f"Counter receivable (card/UPI awaiting payout): {recv:,.2f}   ·   F2 invoice · F4 close day")

    def _add_to_cart(self):
        d = self._item.currentData()
        if not d or self._qty.value() <= 0:
            return
        self._cart.append((d[0], self._qty.value(), self._price.value(), self._item.currentText()))
        self._render_cart()

    def _clear_cart(self):
        self._cart = []
        self._render_cart()

    def _render_cart(self):
        t = self._cart_tbl
        t.setRowCount(len(self._cart))
        subtotal = 0.0
        for i, (iid, q, p, label) in enumerate(self._cart):
            amt = q * p
            t.setItem(i, 0, _item(label))
            t.setItem(i, 1, _item(f"{q:g}", right=True))
            t.setItem(i, 2, _item(f"{p:.2f}", right=True))
            t.setItem(i, 3, _item(f"{amt:.2f}", right=True))
            subtotal += amt
        rate = self.ss._tax_rate()
        tax = round(subtotal * rate / 100, 2)
        self._totals.setText(f"Subtotal {subtotal:,.2f}   Tax {tax:,.2f}   Total {subtotal + tax:,.2f}")

    def _complete(self):
        if not self._cart:
            QMessageBox.information(self, "Sale", "Cart is empty."); return
        subtotal = round(sum(q * p for _, q, p, _ in self._cart), 2)
        rate = self.ss._tax_rate()
        total = round(subtotal * (1 + rate / 100), 2)
        lines = [(iid, q, p) for iid, q, p, _ in self._cart]
        try:
            self.ss.record_counter_sale(lines, [(self._tender.currentText(), total)],
                                        sale_date=QDate.currentDate().toString("yyyy-MM-dd"))
            self._clear_cart()
            self.refresh()
            QMessageBox.information(self, "Sale", f"Sale recorded · {total:,.2f} ({self._tender.currentText()})")
        except Exception as e:
            QMessageBox.critical(self, "Sale", str(e))

    def _close_day(self):
        today = QDate.currentDate().toString("yyyy-MM-dd")
        try:
            d = self.ss.close_day(today)
        except Exception as e:
            QMessageBox.information(self, "Close day", str(e)); return
        self.refresh()
        QMessageBox.information(self, "Day closed",
            f"Daily invoice {d['voucher_no']}\nSubtotal {d['subtotal']:,.2f}  Tax {d['tax']:,.2f}\n"
            f"Cash {d['tenders']['CASH']:,.2f}  Card {d['tenders']['CARD']:,.2f}  UPI {d['tenders']['UPI']:,.2f}\n"
            f"Outstanding (card/UPI to settle): {d['outstanding']:,.2f}")

    def _new_invoice(self):
        if not self.se.s.execute("SELECT 1 FROM store_items WHERE active=1 LIMIT 1").fetchone():
            QMessageBox.information(self, "Invoice", "Add items first (Inventory · F2)."); return
        items = self.se.s.execute(
            "SELECT id, sku, name, sale_price FROM store_items WHERE active=1 ORDER BY name").fetchall()
        dlg = _InvoiceDialog(items, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.values()
            try:
                cust = self.ss.add_customer(
                    d["customer"], phone=d["phone"], email=d["email"],
                    terms=d["terms"], credit_limit=d["credit_limit"])
                row = self.se.s.execute(
                    "SELECT id FROM store_customers WHERE name=?", (d["customer"],)).fetchone()
                res = self.ss.create_invoice(cust, d["lines"],
                                             sale_date=QDate.currentDate().toString("yyyy-MM-dd"),
                                             customer_id=(row["id"] if row else None))
                self.refresh()
                QMessageBox.information(self, "Invoice", f"{res['invoice_no']} · total {res['total']:,.2f}")
            except Exception as e:
                QMessageBox.critical(self, "Invoice", str(e))


class _InvoiceDialog(QDialog):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New invoice")
        self.setMinimumWidth(540)
        self._lines = []
        root = QVBoxLayout(self)
        top = QFormLayout()
        self._cust = QLineEdit(); self._cust.setPlaceholderText("Customer name")
        self._phone = QLineEdit(); self._email = QLineEdit(); self._terms = QLineEdit()
        self._credit = QDoubleSpinBox(); self._credit.setRange(0, 1e9); self._credit.setDecimals(2)
        top.addRow(make_label("Customer", required=True), self._cust)
        top.addRow(make_label("Phone"), self._phone)
        top.addRow(make_label("Email"), self._email)
        top.addRow(make_label("Terms"), self._terms)
        top.addRow(make_label("Credit limit"), self._credit)
        root.addLayout(top)
        addrow = QHBoxLayout()
        self._item = QComboBox()
        for r in items:
            self._item.addItem(f"{r['sku']} — {r['name']}", (r["id"], r["sale_price"]))
        self._qty = QDoubleSpinBox(); self._qty.setRange(0, 1e6); self._qty.setValue(1)
        self._price = QDoubleSpinBox(); self._price.setRange(0, 1e7); self._price.setDecimals(2)
        self._item.currentIndexChanged.connect(
            lambda: self._price.setValue(float((self._item.currentData() or (0, 0))[1] or 0)))
        addrow.addWidget(self._item, 2)
        addrow.addWidget(make_label("Qty")); addrow.addWidget(self._qty)
        addrow.addWidget(make_label("Price")); addrow.addWidget(self._price)
        addrow.addWidget(chip_btn("＋ line", "Add line", self._add))
        root.addLayout(addrow)
        self._tbl = QTableWidget(); self._tbl.setColumnCount(4)
        self._tbl.setHorizontalHeaderLabels(["Item", "Qty", "Price", "Amount"])
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tbl.verticalHeader().setVisible(False)
        root.addWidget(self._tbl, 1)
        btn = QHBoxLayout(); btn.addStretch()
        c = QPushButton("Cancel"); c.clicked.connect(self.reject); btn.addWidget(c)
        ok = QPushButton("Create"); ok.setObjectName("btn_primary"); ok.clicked.connect(self._ok); btn.addWidget(ok)
        root.addLayout(btn)

    def _add(self):
        d = self._item.currentData()
        if not d or self._qty.value() <= 0:
            return
        self._lines.append((d[0], self._qty.value(), self._price.value(), self._item.currentText()))
        self._tbl.setRowCount(len(self._lines))
        for i, (iid, q, p, label) in enumerate(self._lines):
            self._tbl.setItem(i, 0, _item(label))
            self._tbl.setItem(i, 1, _item(f"{q:g}", right=True))
            self._tbl.setItem(i, 2, _item(f"{p:.2f}", right=True))
            self._tbl.setItem(i, 3, _item(f"{q * p:.2f}", right=True))

    def _ok(self):
        if not self._cust.text().strip() or not self._lines:
            QMessageBox.warning(self, "Invoice", "Customer and at least one line required."); return
        self.accept()

    def values(self):
        return {"customer": self._cust.text().strip(),
                "phone": self._phone.text().strip(), "email": self._email.text().strip(),
                "terms": self._terms.text().strip(), "credit_limit": self._credit.value(),
                "lines": [(iid, q, p) for iid, q, p, _ in self._lines]}
