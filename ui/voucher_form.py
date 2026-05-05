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
    ("SALES",       "Income",     "📈"),
    ("PURCHASE",    "Expense",    "📤"),
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
        self._income_ledgers    = []
        self._expense_ledgers   = []
        self._party_ledgers     = []
        self._bank_cash         = []
        self._party_bank_cash   = []
        self._income_group_ids  = []
        self._expense_group_ids = []
        self._load_filtered_ledgers()
        self._journal_rows: list[VoucherLineRow] = []
        self._build_ui()
        self._wire_shortcuts()

    def _load_filtered_ledgers(self):
        try:
            self._income_ledgers    = self.tree.get_income_ledgers()
            self._expense_ledgers   = self.tree.get_expense_ledgers()
            self._party_ledgers     = self.tree.get_party_ledgers()
            self._bank_cash         = self.tree.get_bank_cash_ledgers()
            self._party_bank_cash   = self.tree.get_party_and_bank_cash()
            self._income_group_ids  = self.tree.get_income_group_ids()
            self._expense_group_ids = self.tree.get_expense_group_ids()
        except Exception:
            pass

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
        from ui.widgets import FilteredLedgerSearchEdit
        page = QWidget()
        self._smart_layout = QVBoxLayout(page)
        self._smart_layout.setContentsMargins(0, 0, 0, 0)
        self._smart_layout.setSpacing(8)

        frame = QFrame()
        frame.setObjectName("card")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        inner = QGridLayout(frame)
        inner.setSpacing(14)
        inner.setContentsMargins(16, 16, 16, 16)
        inner.setColumnStretch(0, 0)
        inner.setColumnStretch(1, 1)
        inner.setColumnMinimumWidth(0, 140)

        # Row 0: Field 1 (label + widget — swapped per type by _select_type)
        self._field1_label = QLabel("Account")
        self._field1_label.setObjectName("field_label")
        self._field1_label.setWordWrap(True)
        self._field1_label.setFixedWidth(140)
        inner.addWidget(self._field1_label, 0, 0)
        self.field1_ledger = LedgerSearchEdit(
            self.tree, self.calculator, "Search account..."
        )
        inner.addWidget(self.field1_ledger, 0, 1)

        # Row 1: Field 2
        self._field2_label = QLabel("Account")
        self._field2_label.setObjectName("field_label")
        self._field2_label.setWordWrap(True)
        self._field2_label.setFixedWidth(140)
        inner.addWidget(self._field2_label, 1, 0)
        self.field2_ledger = LedgerSearchEdit(
            self.tree, self.calculator, "Search account..."
        )
        inner.addWidget(self.field2_ledger, 1, 1)

        # Row 2: Amount + GST
        self._amount_label = QLabel("Amount (Rs.)")
        self._amount_label.setObjectName("field_label")
        self._amount_label.setWordWrap(True)
        self._amount_label.setFixedWidth(140)
        inner.addWidget(self._amount_label, 2, 0)

        amt_row = QHBoxLayout()
        self.amount_edit = AmountEdit()
        self.amount_edit.setMinimumWidth(160)
        self.amount_edit.valueChanged.connect(self._update_balance_smart)
        self.amount_edit.focused.connect(self.calculator.connect_to)
        amt_row.addWidget(self.amount_edit)

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

        self._smart_frame = frame
        self._smart_inner = inner
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
            ("Type",           0, True),
            ("Ledger Account", 3, True),
            ("Amount",         1, True),
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
        from core.config import get_dr_label, get_cr_label
        from ui.widgets import FilteredLedgerSearchEdit

        self._current_type = vtype

        for vt, btn in self._type_btns.items():
            btn.setChecked(vt == vtype)

        is_journal = vtype == "JOURNAL"
        has_gst    = vtype in ("SALES", "PURCHASE", "DEBIT_NOTE", "CREDIT_NOTE")

        self._stack.setCurrentIndex(1 if is_journal else 0)
        self._gst_label.setVisible(has_gst)
        self._gst_combo.setVisible(has_gst)

        # Remove old field widgets from grid
        old1 = self._smart_inner.itemAtPosition(0, 1)
        old2 = self._smart_inner.itemAtPosition(1, 1)
        if old1 and old1.widget():
            old1.widget().setParent(None)
        if old2 and old2.widget():
            old2.widget().setParent(None)

        # Build correct filtered fields per voucher type
        if vtype == "SALES":
            self._field1_label.setText("Source of Income")
            self._field2_label.setText("Billed to / Received by")
            f1 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._income_ledgers,
                self._income_group_ids,
                "Search income account...",
            )
            f2 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._party_bank_cash,
                placeholder="Customer, Cash or Bank...",
            )

        elif vtype == "PURCHASE":
            self._field1_label.setText("Expense Account")
            self._field2_label.setText("Paid via / Payable to")
            f1 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._expense_ledgers,
                self._expense_group_ids,
                "Search expense account...",
            )
            f2 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._party_bank_cash,
                placeholder="Cash, Bank or Party...",
            )

        elif vtype == "PAYMENT":
            self._field1_label.setText("Paid to (Party)")
            self._field2_label.setText("Paid from")
            f1 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._party_ledgers,
                placeholder="Search party...",
            )
            f2 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._bank_cash,
                placeholder="Cash or Bank...",
            )

        elif vtype == "RECEIPT":
            self._field1_label.setText("Received from")
            self._field2_label.setText("Deposited to")
            f1 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._party_ledgers,
                placeholder="Search party...",
            )
            f2 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._bank_cash,
                placeholder="Cash or Bank...",
            )

        elif vtype == "CONTRA":
            self._field1_label.setText("From Account")
            self._field2_label.setText("To Account")
            f1 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._bank_cash,
                placeholder="Cash or Bank...",
            )
            f2 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._bank_cash,
                placeholder="Cash or Bank...",
            )

        else:
            # Debit Note, Credit Note, and other fallbacks
            self._field1_label.setText(get_dr_label(short=True) + " Account")
            self._field2_label.setText(get_cr_label(short=True) + " Account")
            f1 = LedgerSearchEdit(
                self.tree, self.calculator, "Search account..."
            )
            f2 = LedgerSearchEdit(
                self.tree, self.calculator, "Search account..."
            )

        self.field1_ledger = f1
        self.field2_ledger = f2
        self._smart_inner.addWidget(f1, 0, 1)
        self._smart_inner.addWidget(f2, 1, 1)

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
        # License gate — check before doing any work
        try:
            from core.license_manager import LicenseManager
            _lmgr = LicenseManager()
            _allowed, _msg, _cost = _lmgr.can_post_voucher()
            if not _allowed:
                QMessageBox.warning(self, "Limit reached", _msg)
                return
            if _msg:  # overage warning on paid plans
                reply = QMessageBox.question(
                    self, "Overage charge applies",
                    f"{_msg}\n\nPost anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
        except Exception:
            pass  # license check failure is non-fatal

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
                f1_id  = self.field1_ledger.selected_id
                f2_id  = self.field2_ledger.selected_id
                amount = self.amount_edit.value()

                if not f1_id:
                    QMessageBox.warning(
                        self, "Missing",
                        f"Please select {self._field1_label.text()}"
                    )
                    return
                if not f2_id:
                    QMessageBox.warning(
                        self, "Missing",
                        f"Please select {self._field2_label.text()}"
                    )
                    return
                if amount <= 0:
                    QMessageBox.warning(
                        self, "Missing",
                        "Amount must be greater than zero."
                    )
                    return

                if vtype == "SALES":
                    dr_id = f2_id   # Billed to / Received by
                    cr_id = f1_id   # Source of income
                    draft = self.engine.build_sales(
                        vdate, dr_id, cr_id, amount, gst_rate, narration, reference
                    )
                elif vtype == "PURCHASE":
                    dr_id = f1_id   # Expense account
                    cr_id = f2_id   # Paid via
                    draft = self.engine.build_purchase(
                        vdate, cr_id, dr_id, amount, gst_rate, narration, reference
                    )
                elif vtype == "PAYMENT":
                    dr_id = f1_id   # Paid to party
                    cr_id = f2_id   # Paid from bank/cash
                    draft = self.engine.build_payment(
                        vdate, dr_id, cr_id, amount, narration, reference
                    )
                elif vtype == "RECEIPT":
                    cr_id = f1_id   # Received from
                    dr_id = f2_id   # Deposited to
                    draft = self.engine.build_receipt(
                        vdate, cr_id, dr_id, amount, narration, reference
                    )
                elif vtype == "CONTRA":
                    cr_id = f1_id   # From account
                    dr_id = f2_id   # To account
                    draft = self.engine.build_contra(
                        vdate, cr_id, dr_id, amount, narration
                    )
                else:
                    dr_id = f1_id
                    cr_id = f2_id
                    draft = self.engine.build_payment(
                        vdate, dr_id, cr_id, amount, narration, reference
                    )

            posted = self.engine.post(draft)

            # Record transaction for license counter
            try:
                from core.license_manager import LicenseManager
                LicenseManager().record_voucher_posted()
            except Exception:
                pass

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
        try:
            self.field1_ledger.clear()
            self.field2_ledger.clear()
        except Exception:
            pass
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
