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
    QScrollArea, QFrame, QSizePolicy, QMessageBox, QStackedWidget,
    QSpacerItem
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
        # Edit-mode state — set via load_voucher_for_edit()
        self._edit_voucher_id: int | None = None
        self._edit_voucher_number: str = ""
        # Create-mode state — set via prefill_for_create() for posting from
        # other pages (Ledger Reconciliation etc.). on_post_callback runs
        # after a successful engine.post(), receiving the PostedVoucher.
        # Type selector stays visible — re-applies prefill on every switch.
        self._create_callback         = None
        self._create_banner_text: str = ""
        self._create_prefill          = None
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

        # ── Header strip (title + hint + subtitle) — hidden in edit mode ──
        self._header_strip = QWidget()
        hs = QVBoxLayout(self._header_strip)
        hs.setContentsMargins(0, 0, 0, 0)
        hs.setSpacing(0)

        hdr = QHBoxLayout()
        title = QLabel("Post Voucher")
        title.setObjectName("page_title")
        hdr.addWidget(title)
        hdr.addStretch()
        hints = QLabel("F2 = New ledger  |  Alt+C = Calculator  |  Ctrl+S = Post")
        hints.setStyleSheet(f"color:{THEME['text_dim']}; font-size:10px;")
        hdr.addWidget(hints)
        hs.addLayout(hdr)

        sub = QLabel("Select voucher type, fill details, post with Ctrl+S")
        sub.setObjectName("page_subtitle")
        hs.addWidget(sub)
        root.addWidget(self._header_strip)

        # ── Edit-mode banner (hidden in create mode) ──
        self._edit_banner = QFrame()
        self._edit_banner.setObjectName("card")
        self._edit_banner.setStyleSheet(
            f"#card {{ background:{THEME['accent_dim']}; "
            f"border:1px solid {THEME['accent']}; }}"
        )
        eb = QHBoxLayout(self._edit_banner)
        eb.setContentsMargins(14, 8, 14, 8)
        self._edit_banner_label = QLabel("")
        self._edit_banner_label.setStyleSheet(
            f"color:{THEME['accent']}; font-weight:bold; font-size:12px;"
        )
        eb.addWidget(self._edit_banner_label)
        eb.addStretch()
        cancel_edit = QPushButton("Cancel edit")
        cancel_edit.setFixedHeight(28)
        cancel_edit.clicked.connect(self._cancel_edit)
        eb.addWidget(cancel_edit)
        self._edit_banner.setVisible(False)
        root.addWidget(self._edit_banner)

        # ── Voucher type selector ──
        type_frame = QFrame()
        type_frame.setObjectName("card")
        self._type_frame = type_frame   # hidden in edit mode
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
        self.date_edit.setFixedHeight(34)
        self.date_edit.setDisplayFormat("dd-MMM-yyyy")
        date_col.addWidget(self.date_edit)
        meta_layout.addLayout(date_col)

        # Narration
        narr_col = QVBoxLayout()
        narr_col.setSpacing(3)
        narr_col.addWidget(make_label("Narration"))
        self.narration_edit = QLineEdit()
        self.narration_edit.setPlaceholderText("e.g. Rent for May 2025")
        self.narration_edit.setFixedHeight(34)
        narr_col.addWidget(self.narration_edit)
        meta_layout.addLayout(narr_col, 3)

        # Reference
        ref_col = QVBoxLayout()
        ref_col.setSpacing(3)
        ref_col.addWidget(make_label("Reference / Cheque No."))
        self.reference_edit = QLineEdit()
        self.reference_edit.setPlaceholderText("Optional")
        self.reference_edit.setFixedHeight(34)
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

        # After picking the GST rate, Tab should land on Post so the user
        # can verify the highlighted Total before submitting.
        self.setTabOrder(self.amount_edit, self._gst_combo)
        self.setTabOrder(self._gst_combo, self._post_btn)

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
        inner = QVBoxLayout(frame)
        inner.setSpacing(0)
        inner.setContentsMargins(22, 22, 22, 22)

        # Each row is a real QWidget with min-height — guarantees a visible
        # vertical gap regardless of how Qt sums contained widgets.
        ROW_HEIGHT     = 54   # 36 input + 18 breathing
        TOTAL_ROW_HEIGHT = 64

        def _make_row(label_widget: QLabel, input_widget,
                      min_height: int = ROW_HEIGHT):
            row_w = QWidget()
            row_w.setMinimumHeight(min_height)
            row_w.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            hl = QHBoxLayout(row_w)
            hl.setContentsMargins(0, 9, 0, 9)
            hl.setSpacing(14)
            hl.addWidget(label_widget, 0)
            if isinstance(input_widget, QHBoxLayout):
                hl.addLayout(input_widget, 1)
            else:
                hl.addWidget(input_widget, 1)
            return row_w

        # Row 1: Field 1
        self._field1_label = QLabel("Account")
        self._field1_label.setFixedWidth(160)
        self._field1_label.setFixedHeight(34)
        self._field1_label.setWordWrap(True)
        self._field1_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft |
            Qt.AlignmentFlag.AlignVCenter
        )
        self._field1_label.setStyleSheet(f"""
            color: {THEME['text_primary']};
            font-size: 12px;
            font-weight: bold;
            background: {THEME['bg_input']};
            border-radius: 7px;
            padding: 0px 10px;
        """)
        self.field1_ledger = LedgerSearchEdit(
            self.tree, self.calculator, "Search account..."
        )
        self._field1_row = _make_row(self._field1_label, self.field1_ledger)
        inner.addWidget(self._field1_row)

        # Row 2: Field 2
        self._field2_label = QLabel("Account")
        self._field2_label.setFixedWidth(160)
        self._field2_label.setFixedHeight(34)
        self._field2_label.setWordWrap(True)
        self._field2_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft |
            Qt.AlignmentFlag.AlignVCenter
        )
        self._field2_label.setStyleSheet(f"""
            color: {THEME['text_primary']};
            font-size: 12px;
            font-weight: bold;
            background: {THEME['bg_input']};
            border-radius: 7px;
            padding: 0px 10px;
        """)
        self.field2_ledger = LedgerSearchEdit(
            self.tree, self.calculator, "Search account..."
        )
        self._field2_row = _make_row(self._field2_label, self.field2_ledger)
        inner.addWidget(self._field2_row)

        # Row 3: Base Amount (asked first; GST applies on top)
        self._amount_label = QLabel("Amount (Rs.)")
        self._amount_label.setFixedWidth(160)
        self._amount_label.setFixedHeight(34)
        self._amount_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft |
            Qt.AlignmentFlag.AlignVCenter
        )
        self._amount_label.setStyleSheet(f"""
            color: {THEME['text_primary']};
            font-size: 12px;
            font-weight: bold;
            background: {THEME['bg_input']};
            border-radius: 7px;
            padding: 0px 10px;
        """)
        self.amount_edit = AmountEdit()
        self.amount_edit.setMinimumWidth(160)
        self.amount_edit.valueChanged.connect(self._update_balance_smart)
        self.amount_edit.focused.connect(self.calculator.connect_to)
        amt_inner = QHBoxLayout()
        amt_inner.setContentsMargins(0, 0, 0, 0)
        amt_inner.addWidget(self.amount_edit)
        amt_inner.addStretch()
        self._amount_row = _make_row(self._amount_label, amt_inner)
        inner.addWidget(self._amount_row)

        # Row 4: GST Rate + GST Amount + Total Amount on one combined row
        self._gst_label = QLabel("GST")
        self._gst_label.setFixedWidth(160)
        self._gst_label.setFixedHeight(34)
        self._gst_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft |
            Qt.AlignmentFlag.AlignVCenter
        )
        self._gst_label.setStyleSheet(f"""
            color: {THEME['text_primary']};
            font-size: 12px;
            font-weight: bold;
            background: {THEME['bg_input']};
            border-radius: 7px;
            padding: 0px 10px;
        """)

        self._gst_combo = QComboBox()
        self._gst_combo.addItem("No GST", 0)
        for r in GST_RATES:
            self._gst_combo.addItem(f"{r}%", r)
        self._gst_combo.setCurrentIndex(4)  # 18%
        self._gst_combo.setFixedHeight(36)
        self._gst_combo.setFixedWidth(96)
        self._gst_combo.currentIndexChanged.connect(self._update_balance_smart)

        self._gst_amount_value = QLabel("Tax ₹ 0.00")
        self._gst_amount_value.setMinimumHeight(36)
        self._gst_amount_value.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:12px; "
            f"font-weight:bold; padding:0 6px;"
        )

        arrow = QLabel("→  Total")
        arrow.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:11px; padding:0 4px;"
        )

        self._total_amount_value = QLabel("₹ 0.00")
        self._total_amount_value.setMinimumHeight(46)
        self._total_amount_value.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self._total_amount_value.setStyleSheet(
            f"color:{THEME['accent']}; font-size:18px; font-weight:bold; "
            f"background:{THEME['accent_dim']}; "
            f"border:1.5px solid {THEME['accent']}; "
            f"border-radius:8px; padding:8px 16px;"
        )

        self._total_hint = QLabel("← post this")
        self._total_hint.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:10px; font-style:italic;"
        )

        gst_total_inner = QHBoxLayout()
        gst_total_inner.setContentsMargins(0, 0, 0, 0)
        gst_total_inner.setSpacing(10)
        gst_total_inner.addWidget(self._gst_combo)
        gst_total_inner.addWidget(self._gst_amount_value)
        gst_total_inner.addWidget(arrow)
        gst_total_inner.addWidget(self._total_amount_value, 1)
        gst_total_inner.addWidget(self._total_hint)

        self._gst_combined_row = _make_row(
            self._gst_label, gst_total_inner,
            min_height=TOTAL_ROW_HEIGHT,
        )
        inner.addWidget(self._gst_combined_row)

        self._smart_layout.addWidget(frame)
        self._smart_layout.addStretch()

        self._smart_frame = frame
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
        # Keep the vertical bar always visible so users see scroll affordance
        # immediately (esp. in edit mode with many lines).
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
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
        self._gst_combined_row.setVisible(has_gst)
        self._amount_label.setText("Base Amount (Rs.)" if has_gst else "Amount (Rs.)")

        # Remove old field widgets from their row layouts
        if self.field1_ledger is not None:
            self._field1_row.layout().removeWidget(self.field1_ledger)
            self.field1_ledger.setParent(None)
        if self.field2_ledger is not None:
            self._field2_row.layout().removeWidget(self.field2_ledger)
            self.field2_ledger.setParent(None)

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

        elif vtype == "DEBIT_NOTE":
            self._field1_label.setText(
                "Dr — Purchase Return"
            )
            self._field2_label.setText(
                "Cr — Supplier / Party"
            )
            f1 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._expense_ledgers,
                self._expense_group_ids,
                "Search purchase/expense account..."
            )
            party_list = (
                self._party_bank_cash
                if self._party_bank_cash
                else self.tree.get_all_ledgers()
            )
            f2 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                party_list,
                placeholder="Supplier, Cash or Bank..."
            )

        elif vtype == "CREDIT_NOTE":
            self._field1_label.setText(
                "Dr — Sales Return"
            )
            self._field2_label.setText(
                "Cr — Customer / Party"
            )
            f1 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                self._income_ledgers,
                self._income_group_ids,
                "Search sales/income account..."
            )
            party_list = (
                self._party_bank_cash
                if self._party_bank_cash
                else self.tree.get_all_ledgers()
            )
            f2 = FilteredLedgerSearchEdit(
                self.tree, self.calculator,
                party_list,
                placeholder="Customer, Cash or Bank..."
            )

        else:
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
        self._field1_row.layout().addWidget(f1, 1)
        self._field2_row.layout().addWidget(f2, 1)
        # Force layout recompute so the new widgets pick up the row geometry.
        self._smart_frame.adjustSize()

        if is_journal and not self._journal_rows:
            self._add_journal_row()
            self._add_journal_row()

        self._update_balance_smart()

        # If we're in create-mode-with-prefill, re-fill so the user sees the
        # party ledger / amount applied to the chosen voucher type.
        if getattr(self, "_create_prefill", None):
            self._apply_create_prefill()

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
        if hasattr(self, "_gst_amount_value"):
            self._gst_amount_value.setText(f"₹ {tax:,.2f}")
            self._total_amount_value.setText(f"₹ {gross:,.2f}")
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

            if self._edit_voucher_id:
                # EDIT mode — replace the existing voucher in place
                posted = self.engine.update_voucher(self._edit_voucher_id, draft)
                self.voucher_posted.emit(
                    posted.voucher_number, vtype, posted.total_amount
                )
                msg = QMessageBox(self)
                msg.setWindowTitle("Updated")
                msg.setText(f"✎  {posted.voucher_number} updated\n₹{posted.total_amount:,.2f}")
                msg.setInformativeText(narration or vtype)
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg.exec()
                self._exit_edit_mode()
                self._clear()
                # Hop back to the page we came from (Ledger Account etc.)
                win = self.window()
                if hasattr(win, "return_from_voucher_edit"):
                    win.return_from_voucher_edit()
                return

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

            # If we were prefilled from another page (Ledger Reconciliation etc.),
            # run the callback so it can link the posted voucher back, then hop
            # to the page we came from.
            cb = self._create_callback
            if cb is not None:
                self._exit_create_mode()
                try:
                    cb(posted)
                except Exception as e:
                    QMessageBox.warning(self, "Post-link failed", str(e))
                self._clear()
                win = self.window()
                if hasattr(win, "return_from_voucher_edit"):
                    win.return_from_voucher_edit()
                return

            self._clear()

        except VoucherValidationError as e:
            QMessageBox.critical(self, "Validation Error",
                "\n".join(f"• {err}" for err in e.errors))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def prefill_for_create(
        self,
        prefill: dict,
        on_post_callback=None,
        banner_text: str = "",
    ) -> None:
        """
        Open the form in create-mode for a fresh voucher, prefilled from
        another page (Ledger / Bank Reconciliation etc.). Posts via the
        normal engine.post path; after success, on_post_callback(posted)
        is called and the page returns to its origin.

        Type selector stays VISIBLE — user picks the voucher type.
        On every type switch, the prefill is re-applied: party ledger
        lands on field1 (PAYMENT/RECEIPT/DEBIT_NOTE/CREDIT_NOTE),
        field2 (SALES/PURCHASE), or as a journal row (JOURNAL).

        prefill keys (all optional):
            voucher_type        — initial pick; defaults to 'JOURNAL'
            voucher_date        — ISO yyyy-mm-dd
            narration / reference
            party_ledger_name   — main subject ledger (the one to be
                                   placed on the canonical side)
            party_amount        — amount; goes into amount_edit on smart
                                   modes / one journal row on JOURNAL
            party_side          — 'DR' or 'CR' — which side the party
                                   ledger should sit on in JOURNAL mode
        """
        # Reset any in-progress edit state
        self._edit_voucher_id     = None
        self._edit_voucher_number = ""

        self._create_callback     = on_post_callback
        self._create_banner_text  = banner_text
        self._create_prefill      = dict(prefill)

        if banner_text:
            self._edit_banner_label.setText(banner_text)
            self._edit_banner.setVisible(True)
            # Hide the page-title strip but KEEP the type selector visible —
            # the user needs it to pick PAYMENT / RECEIPT / SALES / etc.
            self._header_strip.setVisible(False)
        self._post_btn.setText("Post Voucher  (Ctrl+S)")

        vtype = prefill.get("voucher_type") or "JOURNAL"
        self._select_type(vtype)
        # _select_type ends by calling _apply_create_prefill for us
        # (see the hook at the end of _select_type).

    def _apply_create_prefill(self) -> None:
        """
        Re-apply self._create_prefill after a type switch in create-mode.
        Idempotent — safe to call from _select_type's tail.
        """
        from PyQt6.QtCore import QDate
        p = self._create_prefill
        if not p:
            return

        # Form-level fields
        if p.get("voucher_date"):
            self.date_edit.setDate(
                QDate.fromString(p["voucher_date"], "yyyy-MM-dd")
            )
        self.narration_edit.setText(p.get("narration") or "")
        self.reference_edit.setText(p.get("reference") or "")

        party_name = p.get("party_ledger_name") or ""
        party_amt  = float(p.get("party_amount") or 0)
        party_side = (p.get("party_side") or "DR").upper()

        vtype = self._current_type
        if vtype == "JOURNAL":
            # One journal row for the party + a blank row for the counter.
            for r in self._journal_rows[:]:
                self._rows_layout.removeWidget(r)
                r.deleteLater()
            self._journal_rows.clear()
            if party_name and party_amt > 0:
                self._add_journal_row()
                row = self._journal_rows[-1]
                row.ledger_search.set_ledger(party_name)
                row.type_toggle.setCurrentIndex(0 if party_side == "DR" else 1)
                row.amount_edit.setValue(party_amt)
                row.narration.setText(p.get("narration") or "")
            self._add_journal_row()    # blank row for the counter
            self._update_balance_journal()
            return

        # Smart modes — place party in the canonical field for that type.
        # Mapping: party = the subject of the row in the source ledger.
        party_field = self._party_field_for_type(vtype)
        if party_name and party_field:
            getattr(self, party_field).set_ledger(party_name)
        if party_amt > 0:
            self.amount_edit.setValue(party_amt)
        self._update_balance_smart()

    @staticmethod
    def _party_field_for_type(vtype: str) -> str | None:
        """Which smart-mode field receives the prefilled party ledger."""
        # PAYMENT: Field 1 = Paid to (party)
        # RECEIPT: Field 1 = Received from (party)
        # SALES:   Field 2 = Billed to / Received by (party)
        # PURCHASE:Field 2 = Paid via / Payable to (party)
        # DR/CR notes / others: Field 1
        if vtype in ("SALES", "PURCHASE"):
            return "field2_ledger"
        if vtype in ("PAYMENT", "RECEIPT", "DEBIT_NOTE", "CREDIT_NOTE"):
            return "field1_ledger"
        return None

    def _exit_create_mode(self):
        self._create_callback    = None
        self._create_banner_text = ""
        self._create_prefill     = None
        self._edit_banner.setVisible(False)
        self._header_strip.setVisible(True)
        self._type_frame.setVisible(True)

    def load_voucher_for_edit(self, voucher_id: int) -> bool:
        """
        Switch the form into edit-mode for an existing voucher. Returns
        True on success, False if the voucher can't be edited (cancelled
        or has bank-reconciled lines). Always loads in JOURNAL mode so
        every line — ledger, amount, sign, narration — is editable.
        """
        v = self.engine.get_voucher(voucher_id)
        if not v:
            QMessageBox.warning(self, "Not found", f"Voucher {voucher_id} not found.")
            return False
        if v["is_cancelled"]:
            QMessageBox.warning(
                self, "Cannot edit",
                f"Voucher {v['voucher_number']} is cancelled.",
            )
            return False
        if any((l.get("cleared_date") or "") for l in v["lines"]):
            QMessageBox.warning(
                self, "Cannot edit",
                f"Voucher {v['voucher_number']} has bank-reconciled lines.\n"
                "Unmatch in Bank Reconciliation first.",
            )
            return False

        # Reset any in-progress state
        self._edit_voucher_id     = voucher_id
        self._edit_voucher_number = v["voucher_number"]

        # Switch to JOURNAL mode — handles all voucher types uniformly,
        # one row per voucher_line, every column editable.
        self._select_type("JOURNAL")
        # Clear default rows
        for r in self._journal_rows[:]:
            self._rows_layout.removeWidget(r)
            r.deleteLater()
        self._journal_rows.clear()

        # Header fields
        from PyQt6.QtCore import QDate
        self.date_edit.setDate(QDate.fromString(v["voucher_date"], "yyyy-MM-dd"))
        self.narration_edit.setText(v.get("narration") or "")
        self.reference_edit.setText(v.get("reference") or "")

        # Populate one journal row per voucher line
        for line in v["lines"]:
            self._add_journal_row()
            row = self._journal_rows[-1]
            row.ledger_search.set_ledger(line["ledger_name"])
            if (line["dr_amount"] or 0) > 0:
                row.type_toggle.setCurrentIndex(0)        # Dr
                row.amount_edit.setValue(float(line["dr_amount"]))
            else:
                row.type_toggle.setCurrentIndex(1)        # Cr
                row.amount_edit.setValue(float(line["cr_amount"] or 0))
            row.narration.setText(line.get("line_narration") or "")
        self._update_balance_journal()

        # Show edit banner + relabel post button
        self._edit_banner_label.setText(
            f"✎ Editing  {v['voucher_number']}  ·  {v['voucher_type'].replace('_',' ')}"
        )
        self._edit_banner.setVisible(True)
        self._post_btn.setText("Update Voucher  (Ctrl+S)")

        # Hide chrome that's redundant during edit so the row area gets
        # all the vertical space.
        self._header_strip.setVisible(False)
        self._type_frame.setVisible(False)
        return True

    def _exit_edit_mode(self):
        """Drop edit-mode flags + restore chrome + post-button label."""
        self._edit_voucher_id     = None
        self._edit_voucher_number = ""
        self._edit_banner.setVisible(False)
        self._post_btn.setText("Post Voucher  (Ctrl+S)")
        self._header_strip.setVisible(True)
        self._type_frame.setVisible(True)

    def _cancel_edit(self):
        """Handles the banner Cancel button in BOTH edit and create modes."""
        in_edit   = bool(self._edit_voucher_id)
        in_create = bool(self._create_callback or self._create_prefill)
        if not (in_edit or in_create):
            return
        if in_edit:
            self._exit_edit_mode()
        else:
            self._exit_create_mode()
        self._clear()
        self._select_type("PAYMENT")
        win = self.window()
        if hasattr(win, "return_from_voucher_edit"):
            win.return_from_voucher_edit()

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
