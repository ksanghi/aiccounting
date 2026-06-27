"""Store HQ — Dashboard & Reports: KPI cards + report tables that fall out of the
store DB and the books (no bespoke storage; everything is derived)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTabWidget, QTableWidget,
    QAbstractItemView, QHeaderView,
)
from PySide6.QtCore import Qt

from ui.theme import THEME
from ui.table_utils import make_sortable
from ui.store.inventory_page import _item
from ui.store.store_widgets import chip_btn
from core.i18n import format_currency as _fmt


class DashboardPage(QWidget):
    TITLE = "Dashboard & Reports"

    def __init__(self, store_engine, store_sales, parent=None):
        super().__init__(parent)
        self.se = store_engine
        self.ss = store_sales
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel(self.TITLE); title.setObjectName("page_title"); head.addWidget(title)
        head.addStretch()
        head.addWidget(chip_btn("↻", "Refresh", self.refresh))
        root.addLayout(head)

        self._cards = QHBoxLayout()
        self._cards.setSpacing(10)
        root.addLayout(self._cards)

        self._tabs = QTabWidget()
        self._t_val = self._mk_table(["Item", "On hand", "Avg cost", "Stock value"])
        self._t_low = self._mk_table(["Item", "On hand", "Reorder level", "Suggested order"])
        self._t_sales = self._mk_table(["Sale #", "Type", "Date", "Subtotal", "Tax", "Total", "Status"])
        self._t_sup = self._mk_table(["Supplier", "Phone", "Balance (we owe)"])
        self._t_cust = self._mk_table(["Customer", "Phone", "Credit limit", "Balance (owed to us)"])
        self._tabs.addTab(self._t_val, "Stock valuation")
        self._tabs.addTab(self._t_low, "Low stock")
        self._tabs.addTab(self._t_sales, "Sales register")
        self._tabs.addTab(self._t_sup, "Supplier dues")
        self._tabs.addTab(self._t_cust, "Customer balances")
        root.addWidget(self._tabs, 1)

    def _mk_table(self, headers):
        t = QTableWidget()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setAlternatingRowColors(True)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        return t

    def _card(self, label, value, accent=False):
        f = QFrame()
        f.setStyleSheet(
            f"QFrame{{background:{THEME['bg_hover']};border:1px solid {THEME['border']};"
            f"border-radius:12px;}}")
        v = QVBoxLayout(f); v.setContentsMargins(14, 10, 14, 10); v.setSpacing(2)
        val = QLabel(value)
        val.setStyleSheet(f"font-size:20px; font-weight:bold; background:transparent; border:none;"
                          f"color:{THEME['accent'] if accent else THEME['text_primary']};")
        lab = QLabel(label)
        lab.setStyleSheet(f"font-size:11px; color:{THEME['text_secondary']}; background:transparent; border:none;")
        v.addWidget(val); v.addWidget(lab)
        return f

    # ── data ────────────────────────────────────────────────────────────────
    def _ledger_balance(self, ledger_id):
        r = self.se.tree.db.execute(
            "SELECT COALESCE(SUM(dr_amount),0) d, COALESCE(SUM(cr_amount),0) c "
            "FROM voucher_lines WHERE ledger_id=?", (ledger_id,)).fetchone()
        return (r["d"] or 0.0), (r["c"] or 0.0)

    def refresh(self):
        items = self.se.s.execute(
            "SELECT id, sku, name, reorder_level, reorder_qty FROM store_items WHERE active=1 ORDER BY name"
        ).fetchall()
        total_val = 0.0
        low = []
        self._t_val.setSortingEnabled(False)
        self._t_val.setRowCount(len(items))
        for i, r in enumerate(items):
            v = self.se.valuate(r["id"])
            total_val += v["value"]
            self._t_val.setItem(i, 0, _item(f"{r['sku']} — {r['name']}"))
            self._t_val.setItem(i, 1, _item(f"{v['on_hand']:g}", right=True))
            self._t_val.setItem(i, 2, _item(f"{v['avg_cost']:.2f}", right=True))
            self._t_val.setItem(i, 3, _item(f"{v['value']:.2f}", right=True))
            if r["reorder_level"] and v["on_hand"] <= r["reorder_level"]:
                suggest = r["reorder_qty"] or (r["reorder_level"] - v["on_hand"])
                low.append((f"{r['sku']} — {r['name']}", v["on_hand"], r["reorder_level"], suggest))
        make_sortable(self._t_val)

        self._t_low.setSortingEnabled(False)
        self._t_low.setRowCount(len(low))
        for i, (name, oh, rl, sg) in enumerate(low):
            self._t_low.setItem(i, 0, _item(name))
            self._t_low.setItem(i, 1, _item(f"{oh:g}", right=True))
            self._t_low.setItem(i, 2, _item(f"{rl:g}", right=True))
            self._t_low.setItem(i, 3, _item(f"{sg:g}", right=True))
        make_sortable(self._t_low)

        sales = self.se.s.execute(
            "SELECT sale_no, sale_type, sale_date, subtotal, tax, total, status "
            "FROM store_sales ORDER BY id DESC").fetchall()
        self._t_sales.setSortingEnabled(False)
        self._t_sales.setRowCount(len(sales))
        sales_total = 0.0
        for i, r in enumerate(sales):
            sales_total += r["total"] or 0
            self._t_sales.setItem(i, 0, _item(r["sale_no"]))
            self._t_sales.setItem(i, 1, _item(r["sale_type"]))
            self._t_sales.setItem(i, 2, _item(r["sale_date"]))
            self._t_sales.setItem(i, 3, _item(f"{r['subtotal']:.2f}", right=True))
            self._t_sales.setItem(i, 4, _item(f"{r['tax']:.2f}", right=True))
            self._t_sales.setItem(i, 5, _item(f"{r['total']:.2f}", right=True))
            self._t_sales.setItem(i, 6, _item(r["status"] or "—"))
        make_sortable(self._t_sales)

        sups = self.se.s.execute(
            "SELECT name, phone, ledger_id FROM store_suppliers WHERE active=1 ORDER BY name").fetchall()
        self._t_sup.setSortingEnabled(False)
        self._t_sup.setRowCount(len(sups))
        dues = 0.0
        for i, r in enumerate(sups):
            d, c = self._ledger_balance(r["ledger_id"])
            owe = round(c - d, 2)            # creditor: credit balance = we owe
            dues += max(owe, 0)
            self._t_sup.setItem(i, 0, _item(r["name"]))
            self._t_sup.setItem(i, 1, _item(r["phone"] or "—"))
            self._t_sup.setItem(i, 2, _item(f"{owe:.2f}", right=True))
        make_sortable(self._t_sup)

        custs = self.se.s.execute(
            "SELECT name, phone, credit_limit, ledger_id FROM store_customers WHERE active=1 ORDER BY name"
        ).fetchall()
        self._t_cust.setSortingEnabled(False)
        self._t_cust.setRowCount(len(custs))
        recv = 0.0
        for i, r in enumerate(custs):
            d, c = self._ledger_balance(r["ledger_id"])
            bal = round(d - c, 2)            # debtor: debit balance = owed to us
            recv += max(bal, 0)
            self._t_cust.setItem(i, 0, _item(r["name"]))
            self._t_cust.setItem(i, 1, _item(r["phone"] or "—"))
            self._t_cust.setItem(i, 2, _item(f"{r['credit_limit']:.2f}", right=True))
            self._t_cust.setItem(i, 3, _item(f"{bal:.2f}", right=True))
        make_sortable(self._t_cust)

        # KPI cards
        while self._cards.count():
            w = self._cards.takeAt(0).widget()
            if w:
                w.setParent(None)
        counter_recv = self.ss.counter_receivable_balance()
        for lab, val, acc in [
            ("Stock value", _fmt(total_val), True),
            ("Items", str(len(items)), False),
            ("Low stock", str(len(low)), bool(low)),
            ("Counter receivable", _fmt(counter_recv), False),
            ("Supplier dues", _fmt(dues), False),
            ("Customer receivable", _fmt(recv), False),
            ("Sales (all-time)", _fmt(sales_total), False),
        ]:
            self._cards.addWidget(self._card(lab, val, acc))
        self._cards.addStretch()
