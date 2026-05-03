"""
Voucher Entry Form
All 8 voucher types, with:
  - Smart mode  : guided fields (Payment, Receipt, Contra, Sales, Purchase)
  - Journal mode: free-form multi-line DR/CR entry
  - F2          : add ledger on the fly from any ledger field
  - Alt+C      : calculator, result pastes into focused amount field
  - Live balance display: shows Dr total, Cr total, diff in real time
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QDateEdit, QTextEdit,
    QScrollArea, QFrame, QSizePolicy, QMessageBox, QStackedWidget
)
from PyQt6.QtCore import Qt, QDate, pyqtSignal, QTimer
from PyQt6.QtGui  import QFont, QShortcut, QKeySequence

from ui.theme   import THEME, VOUCHER_COLOURS
from ui.widgets import (
    LedgerSearchEdit, AmountEdit, CalculatorWidget,
    VoucherLineRow, make_label, make_separator, StatusPill
)


VOUCHER_TYPES = [
    ("PAYMENT",     "Payment",    "💸"),
    ("RECEIPT",     "Receipt",    "💰"),
    ("CONTRA",      "Contra",     "↔"),
    ("JOURNAL",     "Journal",    "📓"),
    ("SALES",       "Sales",      "🛒"),
    ("PURCHASE",    "Purchase",   "📦"),
    ("DEBIT_NOTE",  "Debit Note", "📋"),
    ("CREDIT_NOTE", "Credit Note","📝"),
]

GST_RATES = [0, 5, 12, 18, 28]


class VoucherEntryPage(QWidget):
    voucher_posted = pyqtSignal(str, str, float)  # type, number, amount

    def __init__(self, engine, tree, calculator: CalculatorWidget, parent=None):
        super().__init__(parent)
        self.engine     = engine
        self.tree       = tree
        self.calculator = calculator
        self._journal_rows: list[VoucherLineRow] = []
        self._build_ui()
        self._wire_shortcuts()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 0, 24, 24)
        root.setSpacing(0)

        # ── Header bar ──
        hdr = QHBoxLayout()
        title = QLabel("Post Voucher")
        title.setObjectName("page_title")
        hdr.addWidget(title)
        hdr.addStretch()

        # Keyboard hints
        hints = QLabel("F2 = New ledger  |  Alt+C = Calculator  |  Ctrl+S = Post")
        hints.setStyleSheet(f"color:{THEME['text_dim']}; font-size:10px;")
        hdr.addWidget(hints)
        root.addLayout(hdr)

        sub = QLabel("Select voucher type, fill details, post with Ctrl+S")
        sub.setObjectName("page_subtitle")
        root.addWidget(sub)

        # ── Voucher type selector ──
        type_frame = QFrame()
        type_frame.setObjectName("card")
        type_layout = QHBoxLayout(type_frame)
        type_layout.setContentsMargins(12, 10, 12, 10)
        type_layout.setSpacing(6)

        self._type_btns: dict[str, QPushButton] = {}
        for vtype, label, icon in VOUCHER_TYPES:
            btn = QPushButton(f"{icon}  {label}")
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            colour = VOUCHER_COLOURS.get(vtype, THEME["accent"])
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {THEME['border']};
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-size: 11px;
                    color: {THEME['text_secondary']};
                }}
                QPushButton:hover {{
                    border-color: {colour};
                    color: {colour};
                }}
                QPushButton:checked {{
                    background: {colour}22;
                    border: 1px solid {colour};
                    color: {colour};
                    font-weight: bold;
                }}
            """)
            btn.clicked.connect(lambda _, vt=vtype: self._select_type(vt))
            type_layout.addWidget(btn)
            self._type_btns[vtype] = btn

        root.addWidget(type_frame)

        # ── Meta row: date, narration, reference ──
        meta_frame = QFrame()
        meta_frame.setObjectName("card")
        meta_layout = QHBoxLayout(meta_frame)
        meta_layout.setContentsMargins(16, 12, 16, 12)
        meta_layout.setSpacing(16)

        # Date
        date_col = QVBoxLayout()
        date_col.setSpacing(3)
        date_col.addWidget(make_label("Voucher Date", required=True))
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setFixedHeight(32)
        self.date_edit.setDisplayFormat("dd-MMM-yyyy")
        date_col.addWidget(self.date_edit)
        meta_layout.addLayout(date_col)

        # Narration
        narr_col = QVBoxLayout()
        narr_col.setSpacing(3)
        narr_col.addWidget(make_label("Narration"))
        self.narration_edit = QLineEdit()
        self.narration_edit.setPlaceholderText("e.g. Rent for May 2025")
        self.narration_edit.setFixedHeight(32)
        narr_col.addWidget(self.narration_edit)
        meta_layout.addLayout(narr_col, 3)

        # Reference
        ref_col = QVBoxLayout()
        ref_col.setSpacing(3)
        ref_col.addWidget(make_label("Reference / Cheque No."))
        self.reference_edit = QLineEdit()
        self.reference_edit.setPlaceholderText("Optional")
        self.reference_edit.setFixedHeight(32)
        ref_col.addWidget(self.reference_edit)
        meta_layout.addLayout(ref_col, 1)

        root.addWidget(meta_frame)

        # ── Stacked: Smart mode vs Journal mode ──
        self._stack = QStackedWidget()

        # Page 0 — Smart mode (guided)
        self._smart_page = self._build_smart_page()
        self._stack.addWidget(self._smart_page)

        # Page 1 — Journal / free mode
        self._journal_page = self._build_journal_page()
        self._stack.addWidget(self._journal_page)

        root.addWidget(self._stack, 1)

        # ── Balance bar + Post button ──
        footer = QHBoxLayout()
        footer.setSpacing(16)

        self._bal_dr = QLabel("Dr  ₹0.00")
        self._bal_cr = QLabel("Cr  ₹0.00")
        self._bal_diff = QLabel("")
        for lbl in (self._bal_dr, self._bal_cr, self._bal_diff):
            lbl.setStyleSheet(f"font-size:11px; color:{THEME['text_secondary']};")

        footer.addStretch()
        footer.addWidget(self._bal_dr)
        sep = QLabel("|")
        sep.setStyleSheet(f"color:{THEME['text_dim']};")
        footer.addWidget(sep)
        footer.addWidget(self._bal_cr)
        footer.addWidget(self._bal_diff)

        self._post_btn = QPushButton("Post Voucher  (Ctrl+S)")
        self._post_btn.setObjectName("btn_primary")
        self._post_btn.setFixedHeight(36)
        self._post_btn.setMinimumWidth(180)
        self._post_btn.clicked.connect(self._post)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedHeight(36)
        self._clear_btn.clicked.connect(self._clear)

        self._calc_btn = QPushButton("🖩  Calc")
        self._calc_btn.setFixedHeight(36)
        self._calc_btn.setFixedWidth(90)
        self._calc_btn.setToolTip("Open calculator (Alt+C / F9)")
        self._calc_btn.clicked.connect(self._show_calculator)
        footer.addWidget(self._calc_btn)
        footer.addWidget(self._clear_btn)
        footer.addWidget(self._post_btn)

        root.addLayout(footer)

        # Select PAYMENT by default
        self._select_type("PAYMENT")

    def _build_smart_page(self) -> QWidget:
        page = QWidget()
        self._smart_layout = QVBoxLayout(page)
        self._smart_layout.setContentsMargins(0, 0, 0, 0)
        self._smart_layout.setSpacing(8)

        frame = QFrame()
        frame.setObjectName("card")
        inner = QGridLayout(frame)
        inner.setSpacing(12)
        inner.setContentsMargins(16, 14, 16, 14)

        # Row 0: Dr ledger
        from core.config import get_dr_label, get_cr_label
        inner.addWidget(make_label(get_dr_label(short=True) + " Account", required=True), 0, 0)
        self.dr_ledger = LedgerSearchEdit(self.tree, self.calculator, "Search Dr ledger…")
        inner.addWidget(self.dr_ledger, 0, 1)

        # Row 1: Cr ledger
        inner.addWidget(make_label(get_cr_label(short=True) + " Account", required=True), 1, 0)
        self.cr_ledger = LedgerSearchEdit(self.tree, self.calculator, "Search Cr ledger…")
        inner.addWidget(self.cr_ledger, 1, 1)

        # Row 2: Amount + GST
        inner.addWidget(make_label("Amount (₹)", required=True), 2, 0)
        amt_row = QHBoxLayout()
        self.amount_edit = AmountEdit()
        self.amount_edit.setMinimumWidth(160)
        self.amount_edit.valueChanged.connect(self._update_balance_smart)
        self.amount_edit.focused.connect(self.calculator.connect_to)

        amt_row.addWidget(self.amount_edit)

        # GST toggle (only for Sales/Purchase)
        self._gst_label = QLabel("GST %")
        self._gst_label.setStyleSheet(f"color:{THEME['text_secondary']};")
        self._gst_combo = QComboBox()
        self._gst_combo.addItem("No GST", 0)
        for r in GST_RATES:
            self._gst_combo.addItem(f"{r}%", r)
        self._gst_combo.setCurrentIndex(4)  # 18%
        self._gst_combo.setFixedWidth(90)
        self._gst_combo.currentIndexChanged.connect(self._update_balance_smart)
        amt_row.addWidget(self._gst_label)
        amt_row.addWidget(self._gst_combo)
        amt_row.addStretch()
        inner.addLayout(amt_row, 2, 1)

        self._smart_layout.addWidget(frame)
        self._smart_layout.addStretch()
        return page

    def _build_journal_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Column headers
        hdr_frame = QFrame()
        hdr_frame.setObjectName("card")
        hdr_row = QHBoxLayout(hdr_frame)
        hdr_row.setContentsMargins(10, 6, 10, 6)
        headers = [
            ("#",              0, False),
            ("Ledger Account", 3, True),
            ("Amount",         1, True),
            ("Type",           1, True),
            ("Line Narration", 2, True),
            ("",               0, False),
        ]
        for col_label, stretch, use_stretch in headers:
            l = QLabel(col_label)
            l.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:10px; font-weight:bold;"
            )
            if use_stretch:
                hdr_row.addWidget(l, stretch)
            else:
                l.setFixedWidth(20 if col_label == "#" else 28)
                hdr_row.addWidget(l)
        layout.addWidget(hdr_frame)

        # Scrollable rows area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        self._rows_layout.addStretch()
        scroll.setWidget(self._rows_container)
        layout.addWidget(scroll, 1)

        # Add row button
        self._add_line_btn = QPushButton("+ Add Line  (Ctrl+Enter)")
        self._add_line_btn.setMinimumHeight(42)
        self._add_line_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_line_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 2px dashed {THEME['border']};
                border-radius: 8px;
                color: {THEME['text_secondary']};
                padding: 8px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {THEME['accent']};
                color: {THEME['accent']};
                background: {THEME['accent_dim']};
            }}
        """)
        self._add_line_btn.clicked.connect(self._add_journal_row)
        layout.addWidget(self._add_line_btn)

        return page

    # ── Logic ─────────────────────────────────────────────────────────────────

    def _select_type(self, vtype: str):
        self._current_type = vtype
        colour = VOUCHER_COLOURS.get(vtype, THEME["accent"])

        for vt, btn in self._type_btns.items():
            btn.setChecked(vt == vtype)

        # Update page title colour
        is_journal = vtype == "JOURNAL"
        has_gst    = vtype in ("SALES", "PURCHASE", "DEBIT_NOTE", "CREDIT_NOTE")

        self._stack.setCurrentIndex(1 if is_journal else 0)

        # Show/hide GST
        self._gst_label.setVisible(has_gst)
        self._gst_combo.setVisible(has_gst)

        # Update Dr/Cr labels based on type
        from core.config import get_dr_label, get_cr_label
        dr = get_dr_label(short=True)
        cr = get_cr_label(short=True)
        labels = {
            "PAYMENT":     (f"Expense / Party — {dr}",    f"Bank / Cash — {cr}"),
            "RECEIPT":     (f"Bank / Cash — {dr}",         f"Party / Income — {cr}"),
            "CONTRA":      (f"To Account — {dr}",          f"From Account — {cr}"),
            "SALES":       (f"Party / Debtor — {dr}",      f"Sales Account — {cr}"),
            "PURCHASE":    (f"Purchase Account — {dr}",    f"Party / Creditor — {cr}"),
            "DEBIT_NOTE":  (f"Party / Creditor — {dr}",   f"Purchase Return — {cr}"),
            "CREDIT_NOTE": (f"Sales Return — {dr}",        f"Party / Debtor — {cr}"),
        }
        dr_hint, cr_hint = labels.get(vtype, ("Debit Account", "Credit Account"))
        self.dr_ledger.search.setPlaceholderText(dr_hint)
        self.cr_ledger.search.setPlaceholderText(cr_hint)

        # If switching to journal, add 2 rows if empty
        if is_journal and not self._journal_rows:
            self._add_journal_row()
            self._add_journal_row()

        self._update_balance_smart()

    def _add_journal_row(self):
        row = VoucherLineRow(
            self.tree, self.calculator,
            row_num=len(self._journal_rows) + 1
        )
        row.delete_requested.connect(self._remove_journal_row)
        row.amount_edit.valueChanged.connect(self._update_balance_journal)
        row.type_toggle.currentIndexChanged.connect(self._update_balance_journal)
        insert_pos = self._rows_layout.count() - 1
        if insert_pos < 0:
            insert_pos = 0
        self._rows_layout.insertWidget(insert_pos, row)
        self._journal_rows.append(row)

    def _remove_journal_row(self, row: VoucherLineRow):
        if len(self._journal_rows) <= 2:
            return  # keep minimum 2 rows
        self._rows_layout.removeWidget(row)
        row.deleteLater()
        self._journal_rows.remove(row)
        # Renumber
        for i, r in enumerate(self._journal_rows, 1):
            r.row_num = i
        self._update_balance_journal()

    def _update_balance_smart(self):
        from core.config import get_dr_label, get_cr_label
        amt = self.amount_edit.value()
        gst = self._gst_combo.currentData() if self._gst_combo.isVisible() else 0
        tax = round(amt * gst / 100, 2)
        gross = round(amt + tax, 2)
        self._bal_dr.setText(f"{get_dr_label(short=True)}  ₹{gross:,.2f}")
        self._bal_cr.setText(f"{get_cr_label(short=True)}  ₹{gross:,.2f}")
        self._bal_diff.setText("✓ Balanced" if gross > 0 else "")
        self._bal_diff.setStyleSheet(f"color:{THEME['success']}; font-size:11px;")

    def _update_balance_journal(self):
        from core.config import get_dr_label, get_cr_label
        total_dr = sum(r.dr_amount for r in self._journal_rows)
        total_cr = sum(r.cr_amount for r in self._journal_rows)
        diff = round(total_dr - total_cr, 2)
        self._bal_dr.setText(f"{get_dr_label(short=True)}  ₹{total_dr:,.2f}")
        self._bal_cr.setText(f"{get_cr_label(short=True)}  ₹{total_cr:,.2f}")
        if abs(diff) < 0.01:
            self._bal_diff.setText("Balanced ✓")
            self._bal_diff.setStyleSheet(
                f"color:{THEME['success']}; font-size:12px; font-weight:bold;"
            )
        else:
            sign = "+" if diff > 0 else ""
            self._bal_diff.setText(f"Diff {sign}₹{diff:,.2f}")
            self._bal_diff.setStyleSheet(
                f"color:{THEME['danger']}; font-size:12px; font-weight:bold;"
            )

    def _get_date_str(self) -> str:
        return self.date_edit.date().toString("yyyy-MM-dd")

    def _post(self):
        from core.voucher_engine import VoucherValidationError, VoucherDraft, VoucherLine

        vtype     = self._current_type
        vdate     = self._get_date_str()
        narration = self.narration_edit.text().strip()
        reference = self.reference_edit.text().strip()
        gst_rate  = self._gst_combo.currentData() if self._gst_combo.isVisible() else 0

        try:
            if vtype == "JOURNAL":
                lines = []
                for row in self._journal_rows:
                    if row.dr_amount > 0 or row.cr_amount > 0:
                        if not row.ledger_id:
                            QMessageBox.warning(self, "Missing ledger",
                                f"Line {row.row_num}: please select a ledger account.")
                            return
                        lines.append(VoucherLine(
                            ledger_id=row.ledger_id,
                            dr_amount=row.dr_amount,
                            cr_amount=row.cr_amount,
                            line_narration=row.narration.text().strip(),
                        ))
                draft = self.engine.build_journal(vdate, lines, narration, reference)

            else:
                dr_id = self.dr_ledger.selected_id
                cr_id = self.cr_ledger.selected_id
                amount = self.amount_edit.value()

                if not dr_id:
                    QMessageBox.warning(self, "Missing field", "Please select a Debit account.")
                    return
                if not cr_id:
                    QMessageBox.warning(self, "Missing field", "Please select a Credit account.")
                    return
                if amount <= 0:
                    QMessageBox.warning(self, "Missing field", "Amount must be greater than zero.")
                    return

                builder_map = {
                    "PAYMENT":     lambda: self.engine.build_payment(vdate, dr_id, cr_id, amount, narration, reference),
                    "RECEIPT":     lambda: self.engine.build_receipt(vdate, dr_id, cr_id, amount, narration, reference),
                    "CONTRA":      lambda: self.engine.build_contra(vdate, cr_id, dr_id, amount, narration),
                    "SALES":       lambda: self.engine.build_sales(vdate, dr_id, cr_id, amount, gst_rate, narration, reference),
                    "PURCHASE":    lambda: self.engine.build_purchase(vdate, dr_id, cr_id, amount, gst_rate, narration, reference),
                    "DEBIT_NOTE":  lambda: self.engine.build_debit_note(vdate, dr_id, cr_id, amount, gst_rate, narration, reference),
                    "CREDIT_NOTE": lambda: self.engine.build_credit_note(vdate, cr_id, dr_id, amount, gst_rate, narration, reference),
                }
                draft = builder_map[vtype]()

            posted = self.engine.post(draft)

            # Success notification
            colour = VOUCHER_COLOURS.get(vtype, THEME["success"])
            self.voucher_posted.emit(posted.voucher_number, vtype, posted.total_amount)

            msg = QMessageBox(self)
            msg.setWindowTitle("Posted")
            msg.setText(f"✓  {posted.voucher_number}\n₹{posted.total_amount:,.2f}")
            msg.setInformativeText(narration or vtype)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()

            self._clear()

        except VoucherValidationError as e:
            QMessageBox.critical(self, "Validation Error",
                "\n".join(f"• {err}" for err in e.errors))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _clear(self):
        self.narration_edit.clear()
        self.reference_edit.clear()
        self.amount_edit.setValue(0)
        self.dr_ledger.clear()
        self.cr_ledger.clear()
        self.date_edit.setDate(QDate.currentDate())
        for row in self._journal_rows[:]:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._journal_rows.clear()
        if self._current_type == "JOURNAL":
            self._add_journal_row()
            self._add_journal_row()
        self._update_balance_smart()

    def apply_label_style(self):
        """Update all live Dr/Cr labels after a style change — no restart needed."""
        for row in self._journal_rows:
            if hasattr(row, '_refresh_toggle_labels'):
                row._refresh_toggle_labels()
        self._select_type(self._current_type)
        self._update_balance_smart()

    def _wire_shortcuts(self):
        from PyQt6.QtGui import QShortcut, QKeySequence
        from PyQt6.QtCore import Qt
        sc_post = QShortcut(QKeySequence("Ctrl+S"), self)
        sc_post.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_post.activated.connect(self._post)
        sc_row = QShortcut(QKeySequence("Ctrl+Return"), self)
        sc_row.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_row.activated.connect(self._add_journal_row)
        for seq in ["Alt+C", "Ctrl+K", "F9"]:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self._show_calculator)

    def _show_calculator(self):
        btn_pos = self._post_btn.mapToGlobal(self._post_btn.rect().topLeft())
        self.calculator.move(btn_pos.x() - 270, btn_pos.y() - 360)
        self.calculator.show()
        self.calculator.raise_()
