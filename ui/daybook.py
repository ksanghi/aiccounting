"""
Day Book panel — lists all vouchers with filter
Ledger Balance panel — searchable ledger summary
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QLineEdit, QComboBox,
    QDateEdit, QFrame, QHeaderView, QAbstractItemView, QSizePolicy,
    QMessageBox,
)
from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtGui  import QColor, QFont, QKeySequence, QShortcut

from ui.theme   import THEME, VOUCHER_COLOURS
from ui.widgets import make_label, make_separator


class DayBookPage(QWidget):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 24)
        layout.setSpacing(8)

        # Title
        title = QLabel("Day Book")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel("All posted vouchers — filter by date, type, or search narration")
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        # Filter bar
        fbar = QFrame()
        fbar.setObjectName("card")
        frow = QHBoxLayout(fbar)
        frow.setContentsMargins(12, 10, 12, 10)
        frow.setSpacing(10)

        frow.addWidget(make_label("From"))
        self.from_date = QDateEdit(QDate(QDate.currentDate().year(), 4, 1))
        self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("dd-MMM-yyyy")
        self.from_date.setFixedHeight(30)
        frow.addWidget(self.from_date)

        frow.addWidget(make_label("To"))
        self.to_date = QDateEdit(QDate.currentDate())
        self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("dd-MMM-yyyy")
        self.to_date.setFixedHeight(30)
        frow.addWidget(self.to_date)

        frow.addWidget(make_label("Type"))
        self.type_filter = QComboBox()
        self.type_filter.addItem("All Types", "")
        for vt in ["PAYMENT","RECEIPT","CONTRA","JOURNAL","SALES","PURCHASE","DEBIT_NOTE","CREDIT_NOTE"]:
            self.type_filter.addItem(vt.replace("_", " ").title(), vt)
        self.type_filter.setFixedHeight(30)
        frow.addWidget(self.type_filter)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search narration…")
        self.search_box.setFixedHeight(30)
        frow.addWidget(self.search_box, 2)

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFixedHeight(30)
        refresh_btn.clicked.connect(self.refresh)
        frow.addWidget(refresh_btn)
        layout.addWidget(fbar)

        # Table
        self.table = QTableWidget()
        self.table.setObjectName("card")
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Date", "Voucher No.", "Type", "Amount", "Narration", "Ref"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        layout.addWidget(self.table, 1)

        # Totals bar
        self.total_label = QLabel("")
        self.total_label.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px; padding:6px 4px;")
        layout.addWidget(self.total_label)

        # Connect filters
        self.from_date.dateChanged.connect(self.refresh)
        self.to_date.dateChanged.connect(self.refresh)
        self.type_filter.currentIndexChanged.connect(self.refresh)
        self.search_box.textChanged.connect(self._filter_table)

    def refresh(self):
        from_d = self.from_date.date().toString("yyyy-MM-dd")
        to_d   = self.to_date.date().toString("yyyy-MM-dd")
        vtype  = self.type_filter.currentData()

        vouchers = self.engine.list_vouchers(
            from_date=from_d, to_date=to_d,
            voucher_type=vtype if vtype else None,
            limit=1000
        )
        self._all_rows = vouchers
        self._populate_table(vouchers)

    def _populate_table(self, vouchers):
        self.table.setRowCount(len(vouchers))
        total = 0.0
        for i, v in enumerate(vouchers):
            colour = VOUCHER_COLOURS.get(v["voucher_type"], THEME["text_secondary"])

            items = [
                v["voucher_date"],
                v["voucher_number"],
                v["voucher_type"].replace("_", " "),
                f"₹{v['total_amount']:,.2f}",
                v["narration"] or "",
                v["reference"] or "",
            ]
            for j, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                                      (Qt.AlignmentFlag.AlignRight if j == 3 else Qt.AlignmentFlag.AlignLeft))
                if j == 2:   # type column — coloured
                    item.setForeground(QColor(colour))
                if v.get("is_cancelled"):
                    item.setForeground(QColor(THEME["text_dim"]))
                self.table.setItem(i, j, item)

            total += v["total_amount"]

        self.total_label.setText(
            f"{len(vouchers)} vouchers  |  Total ₹{total:,.2f}"
        )

    def _filter_table(self, text: str):
        text = text.lower()
        filtered = [
            v for v in self._all_rows
            if text in (v.get("narration") or "").lower()
            or text in (v.get("voucher_number") or "").lower()
            or text in (v.get("reference") or "").lower()
        ]
        self._populate_table(filtered)


class LedgerBalancePage(QWidget):
    def __init__(self, tree, parent=None):
        super().__init__(parent)
        self.tree = tree
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        self._all_data = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 24)
        layout.setSpacing(8)

        title = QLabel("Ledger Balances")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel("Current balance of all accounts. Click a ledger to see its transactions.")
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        # Filter
        fbar = QFrame()
        fbar.setObjectName("card")
        frow = QHBoxLayout(fbar)
        frow.setContentsMargins(12, 10, 12, 10)
        frow.setSpacing(10)

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 Search ledger name…")
        self.search.setFixedHeight(30)
        self.search.textChanged.connect(self._filter)
        frow.addWidget(self.search, 2)

        frow.addWidget(make_label("Group"))
        self.group_filter = QComboBox()
        self.group_filter.addItem("All Groups", "")
        self.group_filter.setFixedHeight(30)
        self.group_filter.currentIndexChanged.connect(self._filter)
        frow.addWidget(self.group_filter, 1)

        self.hide_zero = QPushButton("Hide zero balances")
        self.hide_zero.setCheckable(True)
        self.hide_zero.setChecked(False)
        self.hide_zero.setFixedHeight(30)
        self.hide_zero.clicked.connect(self._filter)
        frow.addWidget(self.hide_zero)

        add_btn = QPushButton("F2 — Add Ledger")
        add_btn.setFixedHeight(30)
        add_btn.setToolTip("F2 — create a new ledger")
        add_btn.clicked.connect(self._add_ledger)
        frow.addWidget(add_btn)

        edit_btn = QPushButton("F3 — Edit")
        edit_btn.setFixedHeight(30)
        edit_btn.setToolTip("F3 — edit the selected ledger")
        edit_btn.clicked.connect(self._edit_selected_ledger)
        frow.addWidget(edit_btn)

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFixedHeight(30)
        refresh_btn.clicked.connect(self.refresh)
        frow.addWidget(refresh_btn)
        layout.addWidget(fbar)

        QShortcut(QKeySequence("F2"), self).activated.connect(self._add_ledger)
        QShortcut(QKeySequence("F3"), self).activated.connect(self._edit_selected_ledger)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Ledger Account", "Group", "Balance", "Dr/Cr"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.doubleClicked.connect(self._edit_selected_ledger)
        layout.addWidget(self.table, 1)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px; padding:6px 4px;")
        layout.addWidget(self.summary_label)

    def refresh(self):
        ledgers = self.tree.get_all_ledgers()

        # Populate group filter
        groups = sorted({l["group_name"] for l in ledgers})
        self.group_filter.clear()
        self.group_filter.addItem("All Groups", "")
        for g in groups:
            self.group_filter.addItem(g, g)

        # Compute balances
        self._all_data = []
        for l in ledgers:
            b = self.tree.get_ledger_balance(l["id"])
            self._all_data.append({
                "id":       l["id"],
                "name":     l["name"],
                "group":    l["group_name"],
                "nature":   l["nature"],
                "balance":  b["balance"],
                "type":     b["type"],
            })

        self._filter()

    def _filter(self):
        search = self.search.text().lower()
        group  = self.group_filter.currentData()
        hide_z = self.hide_zero.isChecked()

        rows = [
            d for d in self._all_data
            if (not search or search in d["name"].lower())
            and (not group  or d["group"] == group)
            and (not hide_z or d["balance"] > 0)
        ]

        self.table.setRowCount(len(rows))
        total_dr = total_cr = 0.0
        for i, d in enumerate(rows):
            is_dr = d["type"] == "Dr"
            colour = THEME["accent"] if is_dr else THEME["warning"]

            items = [d["name"], d["group"], f"₹{d['balance']:,.2f}", d["type"]]
            for j, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignVCenter |
                    (Qt.AlignmentFlag.AlignRight if j >= 2 else Qt.AlignmentFlag.AlignLeft)
                )
                if j >= 2:
                    item.setForeground(QColor(colour))
                if j == 0:
                    item.setData(Qt.ItemDataRole.UserRole, d["id"])
                self.table.setItem(i, j, item)

            if is_dr:
                total_dr += d["balance"]
            else:
                total_cr += d["balance"]

        self.summary_label.setText(
            f"{len(rows)} ledgers  |  "
            f"Total Dr ₹{total_dr:,.2f}  |  Total Cr ₹{total_cr:,.2f}"
        )

    def _add_ledger(self):
        from ui.widgets import QuickAddLedgerDialog
        dlg = QuickAddLedgerDialog(self.tree, parent=self)
        dlg.ledger_created.connect(lambda *_: self.refresh())
        dlg.exec()

    def _edit_selected_ledger(self, *_):
        from ui.widgets import QuickAddLedgerDialog
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "No ledger selected",
                "Pick a ledger from the list, then press F3 to edit it.",
            )
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        lid = item.data(Qt.ItemDataRole.UserRole)
        if not lid:
            return
        dlg = QuickAddLedgerDialog(
            self.tree, parent=self, existing_ledger_id=lid,
        )
        dlg.ledger_updated.connect(lambda *_: self.refresh())
        dlg.exec()
