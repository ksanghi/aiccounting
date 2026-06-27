"""Store HQ — Inventory: item catalog + live on-hand / weighted-avg valuation.
Keyboard-first: F2 = new item, F3 = edit selected, F4 = adjust stock."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QLineEdit, QDialog, QFormLayout, QDoubleSpinBox, QComboBox,
    QCheckBox, QSpinBox, QMessageBox, QAbstractItemView, QHeaderView,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QKeySequence, QShortcut

from ui.theme import THEME
from ui.widgets import make_label, SmartDateEdit
from ui.table_utils import make_sortable, apply_text_filter
from ui.store.store_widgets import chip_btn
from core.date_format import qt_format


def _item(text, right=False):
    it = QTableWidgetItem(str(text))
    it.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                        (Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft))
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return it


class InventoryPage(QWidget):
    TITLE = "Inventory"

    def __init__(self, store_engine, parent=None):
        super().__init__(parent)
        self.se = store_engine
        self._row_ids = []
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
        bar.addWidget(chip_btn("F2  New", "F2 — Add a new item", self._add_item))
        bar.addWidget(chip_btn("F3  Edit", "F3 — Edit the selected item", self._edit_item))
        bar.addWidget(chip_btn("F4  Adjust", "F4 — Adjust stock (count / damage)", self._adjust))
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 Filter items…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda t: apply_text_filter(self._table, t))
        bar.addWidget(self._search, 1)
        bar.addWidget(chip_btn("↻", "Refresh", self.refresh))
        root.addLayout(bar)

        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels(
            ["SKU", "Name", "Category", "Unit", "On hand", "Avg cost", "Value", "Reorder"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.doubleClicked.connect(lambda _: self._edit_item())
        root.addWidget(self._table, 1)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;")
        root.addWidget(self._status)

        QShortcut(QKeySequence("F2"), self).activated.connect(self._add_item)
        QShortcut(QKeySequence("F3"), self).activated.connect(self._edit_item)
        QShortcut(QKeySequence("F4"), self).activated.connect(self._adjust)

    def _categories(self):
        return [r["name"] for r in self.se.s.execute(
            "SELECT name FROM store_categories ORDER BY name").fetchall()]

    def refresh(self):
        rows = self.se.s.execute(
            """SELECT i.id, i.sku, i.name, i.unit, i.reorder_level, c.name AS category
                 FROM store_items i LEFT JOIN store_categories c ON c.id = i.category_id
                WHERE i.active=1 ORDER BY i.name""").fetchall()
        t = self._table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        self._row_ids = []
        total = 0.0
        low = 0
        for i, r in enumerate(rows):
            v = self.se.valuate(r["id"])
            self._row_ids.append(r["id"])
            t.setItem(i, 0, _item(r["sku"]))
            t.setItem(i, 1, _item(r["name"]))
            t.setItem(i, 2, _item(r["category"] or "—"))
            t.setItem(i, 3, _item(r["unit"]))
            t.setItem(i, 4, _item(f"{v['on_hand']:g}", right=True))
            t.setItem(i, 5, _item(f"{v['avg_cost']:.2f}", right=True))
            t.setItem(i, 6, _item(f"{v['value']:.2f}", right=True))
            t.setItem(i, 7, _item(f"{r['reorder_level']:g}" if r["reorder_level"] else "—", right=True))
            total += v["value"]
            if r["reorder_level"] and v["on_hand"] <= r["reorder_level"]:
                low += 1
        make_sortable(t)
        msg = f"{len(rows)} items  ·  stock value {total:,.2f}   ·   F2 new · F3 edit · F4 adjust"
        if low:
            msg += f"  ·  ⚠ {low} at/below reorder"
        self._status.setText(msg)

    def _selected_id(self):
        r = self._table.currentRow()
        if r < 0 or r >= len(self._row_ids):
            return None
        return self._row_ids[r]

    def _items_for_picker(self):
        return self.se.s.execute(
            "SELECT id, sku, name FROM store_items WHERE active=1 ORDER BY name").fetchall()

    def _add_item(self):
        dlg = _ItemDialog(self._categories(), parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.values()
            try:
                self.se.add_item(d.pop("sku"), d.pop("name"), **d)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Add item", str(e))

    def _edit_item(self):
        iid = self._selected_id()
        if not iid:
            QMessageBox.information(self, "Edit item", "Select an item, then press F3.")
            return
        row = self.se.s.execute(
            """SELECT i.*, c.name AS category FROM store_items i
                 LEFT JOIN store_categories c ON c.id = i.category_id WHERE i.id=?""",
            (iid,)).fetchone()
        dlg = _ItemDialog(self._categories(), existing=row, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.values()
            d.pop("sku", None)            # SKU is the identity — not edited here
            try:
                self.se.update_item(iid, **d)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Edit item", str(e))

    def _adjust(self):
        items = self._items_for_picker()
        if not items:
            QMessageBox.information(self, "Adjust stock", "Add an item first (F2).")
            return
        dlg = _AdjustDialog(items, self._selected_id(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.values()
            try:
                self.se.adjust_stock(d["item_id"], d["qty_delta"],
                                     adj_date=d["date"], reason=d["reason"])
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Adjust stock", str(e))


class _ItemDialog(QDialog):
    def __init__(self, categories, existing=None, parent=None):
        super().__init__(parent)
        self._edit = existing is not None
        self.setWindowTitle("Edit item" if self._edit else "New item")
        self.setMinimumWidth(440)
        form = QFormLayout(self)

        self._sku = QLineEdit(); self._barcode = QLineEdit()
        self._name = QLineEdit(); self._desc = QLineEdit()
        self._cat = QComboBox(); self._cat.setEditable(True); self._cat.addItem("")
        for c in categories:
            self._cat.addItem(c)
        self._brand = QLineEdit()
        self._unit = QLineEdit("pc"); self._punit = QLineEdit()
        self._upp = QDoubleSpinBox(); self._upp.setRange(1, 1e6); self._upp.setValue(1)
        self._price = QDoubleSpinBox(); self._price.setMaximum(1e7); self._price.setDecimals(2)
        self._mrp = QDoubleSpinBox(); self._mrp.setMaximum(1e7); self._mrp.setDecimals(2)
        self._minp = QDoubleSpinBox(); self._minp.setMaximum(1e7); self._minp.setDecimals(2)
        self._taxable = QCheckBox("Taxable"); self._taxable.setChecked(True)
        self._reorder = QDoubleSpinBox(); self._reorder.setMaximum(1e7)
        self._reqty = QDoubleSpinBox(); self._reqty.setMaximum(1e7)
        self._maxlvl = QDoubleSpinBox(); self._maxlvl.setMaximum(1e7)

        form.addRow(make_label("SKU", required=True), self._sku)
        form.addRow(make_label("Barcode"), self._barcode)
        form.addRow(make_label("Name", required=True), self._name)
        form.addRow(make_label("Description"), self._desc)
        form.addRow(make_label("Category"), self._cat)
        form.addRow(make_label("Brand"), self._brand)
        form.addRow(make_label("Selling unit"), self._unit)
        form.addRow(make_label("Purchase unit"), self._punit)
        form.addRow(make_label("Units per purchase unit"), self._upp)
        form.addRow(make_label("Sale price"), self._price)
        form.addRow(make_label("MRP / list price"), self._mrp)
        form.addRow(make_label("Min price (floor)"), self._minp)
        form.addRow("", self._taxable)
        form.addRow(make_label("Reorder level"), self._reorder)
        form.addRow(make_label("Reorder qty"), self._reqty)
        form.addRow(make_label("Max level"), self._maxlvl)

        if self._edit:
            self._sku.setText(existing["sku"]); self._sku.setReadOnly(True)
            self._barcode.setText(existing["barcode"] or "")
            self._name.setText(existing["name"]); self._desc.setText(existing["description"] or "")
            self._cat.setCurrentText(existing["category"] or "")
            self._brand.setText(existing["brand"] or "")
            self._unit.setText(existing["unit"] or "pc"); self._punit.setText(existing["purchase_unit"] or "")
            self._upp.setValue(existing["units_per_purchase"] or 1)
            self._price.setValue(existing["sale_price"] or 0)
            self._mrp.setValue(existing["mrp"] or 0); self._minp.setValue(existing["min_price"] or 0)
            self._taxable.setChecked(bool(existing["taxable"]))
            self._reorder.setValue(existing["reorder_level"] or 0)
            self._reqty.setValue(existing["reorder_qty"] or 0)
            self._maxlvl.setValue(existing["max_level"] or 0)

        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject); row.addWidget(cancel)
        ok = QPushButton("Save" if self._edit else "Add"); ok.setObjectName("btn_primary")
        ok.clicked.connect(self._ok); row.addWidget(ok)
        form.addRow(row)

    def _ok(self):
        if not self._sku.text().strip() or not self._name.text().strip():
            QMessageBox.warning(self, "Item", "SKU and Name are required.")
            return
        self.accept()

    def values(self):
        return {"sku": self._sku.text().strip(), "name": self._name.text().strip(),
                "barcode": self._barcode.text().strip(),
                "description": self._desc.text().strip(),
                "category": self._cat.currentText().strip(),
                "brand": self._brand.text().strip(),
                "unit": self._unit.text().strip() or "pc",
                "purchase_unit": self._punit.text().strip(),
                "units_per_purchase": self._upp.value(),
                "sale_price": self._price.value(), "mrp": self._mrp.value(),
                "min_price": self._minp.value(), "taxable": self._taxable.isChecked(),
                "reorder_level": self._reorder.value(), "reorder_qty": self._reqty.value(),
                "max_level": self._maxlvl.value()}


class _AdjustDialog(QDialog):
    def __init__(self, items, preselect_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Adjust stock")
        self.setMinimumWidth(380)
        form = QFormLayout(self)
        self._item = QComboBox()
        for r in items:
            self._item.addItem(f"{r['sku']} — {r['name']}", r["id"])
        if preselect_id is not None:
            i = self._item.findData(preselect_id)
            if i >= 0:
                self._item.setCurrentIndex(i)
        self._qty = QDoubleSpinBox(); self._qty.setRange(-1e6, 1e6); self._qty.setDecimals(2)
        self._date = SmartDateEdit(QDate.currentDate()); self._date.setDisplayFormat(qt_format())
        self._reason = QLineEdit()
        self._reason.setPlaceholderText("e.g. breakage, count correction")
        form.addRow(make_label("Item", required=True), self._item)
        form.addRow(make_label("Qty (+ found / − loss)", required=True), self._qty)
        form.addRow(make_label("Date"), self._date)
        form.addRow(make_label("Reason"), self._reason)
        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject); row.addWidget(cancel)
        ok = QPushButton("Post"); ok.setObjectName("btn_primary"); ok.clicked.connect(self.accept); row.addWidget(ok)
        form.addRow(row)

    def values(self):
        return {"item_id": self._item.currentData(), "qty_delta": self._qty.value(),
                "date": self._date.date().toString("yyyy-MM-dd"),
                "reason": self._reason.text().strip()}
