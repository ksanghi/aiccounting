"""Store HQ — Returns: sale returns (credit note, goods back + revenue reversed)
and purchase returns (debit note, goods back to supplier). F2 = sale return,
F9 = purchase return."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QComboBox, QDoubleSpinBox, QDialog, QFormLayout, QLineEdit, QMessageBox,
    QAbstractItemView, QHeaderView,
)
from PySide6.QtCore import QDate
from PySide6.QtGui import QKeySequence, QShortcut

from ui.theme import THEME
from ui.widgets import make_label, SmartDateEdit
from ui.table_utils import make_sortable
from ui.store.inventory_page import _item
from ui.store.store_widgets import chip_btn
from core.date_format import qt_format


class ReturnsPage(QWidget):
    TITLE = "Returns"

    def __init__(self, store_sales, store_engine, parent=None):
        super().__init__(parent)
        self.ss = store_sales
        self.se = store_engine
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(8)
        title = QLabel(self.TITLE); title.setObjectName("page_title"); root.addWidget(title)

        bar = QHBoxLayout(); bar.setSpacing(6)
        bar.addWidget(chip_btn("F2  Sale return", "F2 — Customer returns goods (credit note)", self._sale_return))
        bar.addWidget(chip_btn("F9  Purchase return", "F9 — Return goods to supplier (debit note)", self._purchase_return))
        bar.addStretch()
        bar.addWidget(chip_btn("↻", "Refresh", self.refresh))
        root.addLayout(bar)

        self._table = QTableWidget(); self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Return #", "Date", "Subtotal", "Tax", "Total"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self._table, 1)
        self._status = QLabel(""); self._status.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;")
        root.addWidget(self._status)

        QShortcut(QKeySequence("F2"), self).activated.connect(self._sale_return)
        QShortcut(QKeySequence("F9"), self).activated.connect(self._purchase_return)

    def refresh(self):
        rows = self.se.s.execute(
            "SELECT sale_no, sale_date, subtotal, tax, total FROM store_sales "
            "WHERE sale_type='RETURN' ORDER BY id DESC").fetchall()
        t = self._table; t.setSortingEnabled(False); t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            t.setItem(i, 0, _item(r["sale_no"]))
            t.setItem(i, 1, _item(r["sale_date"]))
            t.setItem(i, 2, _item(f"{r['subtotal']:.2f}", right=True))
            t.setItem(i, 3, _item(f"{r['tax']:.2f}", right=True))
            t.setItem(i, 4, _item(f"{r['total']:.2f}", right=True))
        make_sortable(t)
        self._status.setText(f"{len(rows)} sale returns   ·   F2 sale return · F9 purchase return")

    def _items(self):
        return self.se.s.execute(
            "SELECT id, sku, name, sale_price FROM store_items WHERE active=1 ORDER BY name").fetchall()

    def _sale_return(self):
        if not self._items():
            QMessageBox.information(self, "Sale return", "Add items first."); return
        custs = self.se.s.execute(
            "SELECT id, name, ledger_id FROM store_customers WHERE active=1 ORDER BY name").fetchall()
        dlg = _SaleReturnDialog(self._items(), custs, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.values()
            try:
                res = self.ss.return_sale(d["lines"], return_date=d["date"],
                                          credit_to=d["credit_to"], ref="sale-return")
                QMessageBox.information(self, "Credit note", f"{res['return_no']} · total {res['total']:,.2f}")
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Sale return", str(e))

    def _purchase_return(self):
        sups = self.se.s.execute(
            "SELECT id, name FROM store_suppliers WHERE active=1 ORDER BY name").fetchall()
        if not sups or not self._items():
            QMessageBox.information(self, "Purchase return", "Need a supplier and items first."); return
        dlg = _PurchaseReturnDialog(self._items(), sups, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.values()
            try:
                res = self.se.purchase_return(d["supplier_id"], d["lines"], date=d["date"])
                QMessageBox.information(self, "Debit note", f"{res['dn_no']} · cost {res['cost']:,.2f}")
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Purchase return", str(e))


class _LineBuilder(QDialog):
    """Shared item/qty(/price) line builder."""

    def __init__(self, title, items, with_price, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self._with_price = with_price
        self._lines = []
        self.root = QVBoxLayout(self)
        self.top = QFormLayout()
        self.root.addLayout(self.top)

        addrow = QHBoxLayout()
        self._item = QComboBox()
        for r in items:
            self._item.addItem(f"{r['sku']} — {r['name']}", (r["id"], r["sale_price"]))
        self._qty = QDoubleSpinBox(); self._qty.setRange(0, 1e6); self._qty.setValue(1)
        addrow.addWidget(self._item, 2)
        addrow.addWidget(make_label("Qty")); addrow.addWidget(self._qty)
        if with_price:
            self._price = QDoubleSpinBox(); self._price.setRange(0, 1e7); self._price.setDecimals(2)
            self._item.currentIndexChanged.connect(
                lambda: self._price.setValue(float((self._item.currentData() or (0, 0))[1] or 0)))
            addrow.addWidget(make_label("Price")); addrow.addWidget(self._price)
        addrow.addWidget(chip_btn("＋ line", "Add line", self._add))
        self.root.addLayout(addrow)

        self._tbl = QTableWidget(); self._tbl.setColumnCount(3 if with_price else 2)
        self._tbl.setHorizontalHeaderLabels(["Item", "Qty", "Price"][:3 if with_price else 2])
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tbl.verticalHeader().setVisible(False)
        self.root.addWidget(self._tbl, 1)

        btn = QHBoxLayout(); btn.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject); btn.addWidget(cancel)
        self._ok_btn = QPushButton("Save"); self._ok_btn.setObjectName("btn_primary")
        self._ok_btn.clicked.connect(self._ok); btn.addWidget(self._ok_btn)
        self.root.addLayout(btn)

    def _add(self):
        d = self._item.currentData()
        if not d or self._qty.value() <= 0:
            return
        price = self._price.value() if self._with_price else 0.0
        self._lines.append((d[0], self._qty.value(), price, self._item.currentText()))
        self._tbl.setRowCount(len(self._lines))
        for i, (iid, q, p, label) in enumerate(self._lines):
            self._tbl.setItem(i, 0, _item(label))
            self._tbl.setItem(i, 1, _item(f"{q:g}", right=True))
            if self._with_price:
                self._tbl.setItem(i, 2, _item(f"{p:.2f}", right=True))

    def _ok(self):
        if not self._lines:
            QMessageBox.warning(self, "Lines", "Add at least one line."); return
        self.accept()


class _SaleReturnDialog(_LineBuilder):
    def __init__(self, items, customers, parent=None):
        super().__init__("Sale return (credit note)", items, with_price=True, parent=parent)
        self._mode = QComboBox()
        self._mode.addItems(["Credit to customer account", "Cash refund", "Bank refund"])
        self._cust = QComboBox()
        for c in customers:
            self._cust.addItem(c["name"], c["ledger_id"])
        self._date = SmartDateEdit(QDate.currentDate()); self._date.setDisplayFormat(qt_format())
        self.top.addRow(make_label("Refund / credit"), self._mode)
        self.top.addRow(make_label("Customer"), self._cust)
        self.top.addRow(make_label("Date"), self._date)
        self._mode.currentIndexChanged.connect(
            lambda: self._cust.setEnabled(self._mode.currentIndex() == 0))

    def _ok(self):
        if self._mode.currentIndex() == 0 and self._cust.count() == 0:
            QMessageBox.warning(self, "Sale return", "No customers — choose a cash/bank refund instead."); return
        super()._ok()

    def values(self):
        if self._mode.currentIndex() == 0:
            credit_to = ("PARTY", self._cust.currentData())
        elif self._mode.currentIndex() == 1:
            credit_to = ("REFUND", ("Cash", "Cash-in-Hand", "cash"))
        else:
            credit_to = ("REFUND", ("Bank Account", "Bank Accounts", "bank"))
        return {"lines": [(iid, q, p) for iid, q, p, _ in self._lines],
                "date": self._date.date().toString("yyyy-MM-dd"), "credit_to": credit_to}


class _PurchaseReturnDialog(_LineBuilder):
    def __init__(self, items, suppliers, parent=None):
        super().__init__("Purchase return (debit note)", items, with_price=False, parent=parent)
        self._sup = QComboBox()
        for s in suppliers:
            self._sup.addItem(s["name"], s["id"])
        self._date = SmartDateEdit(QDate.currentDate()); self._date.setDisplayFormat(qt_format())
        self.top.addRow(make_label("Supplier", required=True), self._sup)
        self.top.addRow(make_label("Date"), self._date)

    def values(self):
        return {"supplier_id": self._sup.currentData(),
                "lines": [(iid, q) for iid, q, _p, _ in self._lines],
                "date": self._date.date().toString("yyyy-MM-dd")}
