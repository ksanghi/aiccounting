"""
Voucher Entry Form
All 8 voucher types, with:
  - Smart mode  : guided fields (Payment, Receipt, Contra, Sales, Purchase)
  - Journal mode: free-form multi-line DR/CR entry
  - F2          : add ledger on the fly from any ledger field
  - Alt+C      : calculator, result pastes into focused amount field
  - Live balance display: shows Dr total, Cr total, diff in real time
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QDateEdit, QTextEdit,
    QScrollArea, QFrame, QSizePolicy, QMessageBox, QStackedWidget,
    QSpacerItem, QFileDialog, QDialog
)
from PySide6.QtCore import Qt, QDate, Signal, QTimer, QThread
from PySide6.QtGui  import QFont, QShortcut, QKeySequence

from ui.theme   import THEME, VOUCHER_COLOURS
from core.date_format import qt_format, format_iso
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


class _AiFillThread(QThread):
    """Parses one document and extracts a single voucher, off the UI thread.
    Used by the in-context 'AI fill from document' button on Sales/Purchase
    entry. `feature` is 'sales_ai_fill' or 'purchase_ai_fill' — both are
    ag_key class, so they route automatically (wallet, or the customer's own
    key) and never hit the locked state."""
    done  = Signal(list)   # list of extracted voucher dicts
    error = Signal(str)

    def __init__(self, filepath, doc_type, feature, ledger_names, company_name):
        super().__init__()
        self.filepath     = filepath
        self.doc_type     = doc_type
        self.feature      = feature
        self.ledger_names = ledger_names
        self.company_name = company_name

    def run(self):
        try:
            from ai.document_parser import DocumentParser
            from ai.voucher_ai      import VoucherAI
            parser = DocumentParser(feature=self.feature)
            result = parser.parse(self.filepath)
            if not result.success:
                self.error.emit(
                    result.error or "Could not extract text from document."
                )
                return
            ai = VoucherAI(feature=self.feature)
            vouchers = ai.extract_vouchers(
                result.full_text, self.ledger_names,
                self.doc_type, self.company_name,
            )
            self.done.emit(vouchers)
        except Exception as e:
            self.error.emit(str(e))


class _MultiPartyVoucherDialog(QDialog):
    """
    Multi-party Payment / Receipt voucher entry.

    Single bank-or-cash line on one side, N party lines on the other —
    used when a bank transaction settles multiple parties at once (e.g.
    a single bank debit covering 5 vendor payments, or a single deposit
    covering 5 customer receipts).

    On accept(), posts the voucher via engine.build_payment_multi /
    build_receipt_multi + engine.post(), records the license counter, and
    emits posted via the `posted` signal.
    """
    posted = Signal(object)   # PostedVoucher

    def __init__(self, engine, tree, vtype: str,
                 default_date: str, default_bank_id: int | None,
                 party_ledgers: list, bank_ledgers: list,
                 calculator, parent=None):
        super().__init__(parent)
        self.engine    = engine
        self.tree      = tree
        self.vtype     = vtype     # "PAYMENT" or "RECEIPT"
        self.calculator = calculator
        self._party_ledgers = party_ledgers
        self._bank_ledgers  = bank_ledgers
        self._rows: list[dict] = []   # each: {row_widget, ledger, amount, narr}

        is_payment = vtype == "PAYMENT"
        self.setWindowTitle("Multi-party " + ("Payment" if is_payment else "Receipt"))
        self.setMinimumSize(820, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel(
            ("Pay multiple parties from one bank/cash account."
             if is_payment else
             "Receive from multiple parties into one bank/cash account.")
            + " Add a row per party; the bank total auto-sums."
        )
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:12px;")
        layout.addWidget(title)

        # ── Header: date + bank/cash + narration + reference ──
        from ui.widgets import SmartDateEdit, FilteredLedgerSearchEdit
        head = QGridLayout()
        head.setHorizontalSpacing(14)
        head.setVerticalSpacing(8)

        head.addWidget(make_label("Voucher Date", required=True), 0, 0)
        self.date_edit = SmartDateEdit(QDate.fromString(default_date, "yyyy-MM-dd"))
        self.date_edit.setFixedHeight(34)
        self.date_edit.setDisplayFormat(qt_format())
        head.addWidget(self.date_edit, 1, 0)

        bank_label = "Paid from" if is_payment else "Deposited to"
        head.addWidget(make_label(bank_label, required=True), 0, 1)
        self.bank_field = FilteredLedgerSearchEdit(
            tree, calculator, self._bank_ledgers,
            placeholder="Cash or Bank...",
        )
        if default_bank_id:
            try:
                name = next(
                    (l["name"] for l in self._bank_ledgers if l["id"] == default_bank_id),
                    "",
                )
                if name:
                    self.bank_field.search.setText(name)
                    self.bank_field._selected_id = default_bank_id
            except Exception:
                pass
        head.addWidget(self.bank_field, 1, 1)

        head.addWidget(make_label("Narration"), 0, 2)
        self.narration_edit = QLineEdit()
        self.narration_edit.setFixedHeight(34)
        self.narration_edit.setPlaceholderText(
            "Optional — applied to whole voucher"
        )
        head.addWidget(self.narration_edit, 1, 2)

        head.addWidget(make_label("Reference"), 0, 3)
        self.reference_edit = QLineEdit()
        self.reference_edit.setFixedHeight(34)
        self.reference_edit.setPlaceholderText("Chq # / UTR")
        head.addWidget(self.reference_edit, 1, 3)

        head.setColumnStretch(2, 2)
        head.setColumnStretch(3, 1)
        layout.addLayout(head)

        # ── Rows area ──
        rows_hdr = QHBoxLayout()
        rows_hdr.addWidget(make_label(
            "Party" if is_payment else "From Party"
        ))
        rows_hdr.addStretch()
        rows_hdr.addWidget(make_label("Amount (Rs.)"))
        layout.addLayout(rows_hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rows_wrap = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_wrap)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addStretch()
        scroll.setWidget(self._rows_wrap)
        layout.addWidget(scroll, 1)

        # Add row button
        add_btn = QPushButton("+ Add party row")
        add_btn.setMinimumHeight(36)
        add_btn.clicked.connect(self._add_row)
        layout.addWidget(add_btn)

        # Footer — bento mini-tile row: Lines / Total / Balance + Save row.
        try:
            from ui.bento_widgets import BentoFooter
            self._bento_footer = BentoFooter()
            self._tile_lines = self._bento_footer.add_tile("Lines", "0")
            self._tile_total = self._bento_footer.add_tile(
                "Total receipts" if not is_payment else "Total payments",
                "₹ 0.00",
            )
            self._tile_balance = self._bento_footer.add_tile(
                "Balance check", "✓ Balanced", status="good",
            )
            self._bento_footer.add_spacer()
            cancel = QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            post_btn = QPushButton("Save voucher")
            post_btn.setObjectName("btn_primary")
            post_btn.clicked.connect(self._post)
            self._bento_footer.add_button(cancel)
            self._bento_footer.add_button(post_btn)
            layout.addWidget(self._bento_footer)
            # Keep the legacy _total_lbl name so other code paths
            # that read it don't break — point it at the total tile.
            self._total_lbl = QLabel("Total ₹ 0.00")
        except Exception:
            # Fallback: old flat footer if bento widgets aren't on path.
            foot = QHBoxLayout()
            self._total_lbl = QLabel("Total ₹ 0.00")
            self._total_lbl.setStyleSheet(
                f"color:{THEME['accent']}; font-size:14px; font-weight:bold;"
            )
            foot.addWidget(self._total_lbl)
            foot.addStretch()
            cancel = QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            post_btn = QPushButton("Post voucher")
            post_btn.setObjectName("btn_primary")
            post_btn.clicked.connect(self._post)
            foot.addWidget(cancel)
            foot.addWidget(post_btn)
            layout.addLayout(foot)
            self._tile_lines = None
            self._tile_total = None
            self._tile_balance = None

        # Seed with 2 empty rows so the user has something to start with.
        self._add_row()
        self._add_row()

    def _add_row(self):
        from ui.widgets import FilteredLedgerSearchEdit
        row_w = QFrame()
        row_w.setObjectName("card")
        rl = QHBoxLayout(row_w)
        rl.setContentsMargins(10, 6, 10, 6)
        rl.setSpacing(8)

        ledger = FilteredLedgerSearchEdit(
            self.tree, self.calculator, self._party_ledgers,
            placeholder="Search party...",
        )
        amount = AmountEdit()
        amount.setMinimumWidth(140)
        amount.valueChanged.connect(self._refresh_total)
        amount.focused.connect(self.calculator.connect_to)
        narr = QLineEdit()
        narr.setFixedHeight(34)
        narr.setPlaceholderText("Line note (optional)")
        rm = QPushButton("✕")
        rm.setFixedSize(32, 34)
        rm.setToolTip("Remove this party row")

        rl.addWidget(ledger, 3)
        rl.addWidget(amount, 1)
        rl.addWidget(narr, 2)
        rl.addWidget(rm)

        # Insert above the trailing stretch
        insert_pos = self._rows_layout.count() - 1
        if insert_pos < 0:
            insert_pos = 0
        self._rows_layout.insertWidget(insert_pos, row_w)

        row_data = {
            "widget": row_w, "ledger": ledger,
            "amount": amount, "narr": narr,
        }
        self._rows.append(row_data)
        rm.clicked.connect(lambda _, r=row_data: self._remove_row(r))
        self._refresh_total()

    def _remove_row(self, row_data: dict):
        if len(self._rows) <= 1:
            return  # keep at least one row
        self._rows_layout.removeWidget(row_data["widget"])
        row_data["widget"].deleteLater()
        self._rows.remove(row_data)
        self._refresh_total()

    def _refresh_total(self):
        total = sum(r["amount"].value() for r in self._rows)
        self._total_lbl.setText(f"Total ₹ {total:,.2f}")
        # Mirror into the bento footer tiles when available.
        try:
            if getattr(self, "_tile_lines", None) is not None:
                self._tile_lines.set_value(str(len(self._rows)))
            if getattr(self, "_tile_total", None) is not None:
                self._tile_total.set_value(f"₹ {total:,.2f}")
            if getattr(self, "_tile_balance", None) is not None:
                # Multi-party always balances by construction (bank leg
                # = sum of party legs). Surface that visually.
                self._tile_balance.set_value(
                    "✓ Balanced" if total > 0 else "—"
                )
        except Exception:
            pass

    def _post(self):
        # License gate (same as VoucherEntryPage)
        try:
            from core.license_manager import LicenseManager
            _lmgr = LicenseManager()
            _allowed, _msg, _cost = _lmgr.can_post_voucher()
            if not _allowed:
                QMessageBox.warning(self, "Limit reached", _msg)
                return
            if _msg:
                reply = QMessageBox.question(
                    self, "Overage charge applies",
                    f"{_msg}\n\nPost anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
        except Exception:
            pass

        bank_id = self.bank_field.selected_id
        if not bank_id:
            QMessageBox.warning(self, "Missing", "Please select the bank / cash account.")
            return

        party_lines = []
        for r in self._rows:
            lid = r["ledger"].selected_id
            amt = r["amount"].value()
            if amt <= 0 and not lid:
                continue  # skip blank rows entirely
            if not lid:
                QMessageBox.warning(self, "Missing party",
                    "Each non-blank row needs a party ledger.")
                return
            if amt <= 0:
                QMessageBox.warning(self, "Missing amount",
                    "Each party row needs an amount greater than zero.")
                return
            if lid == bank_id:
                QMessageBox.warning(self, "Same ledger",
                    "Party ledger can't be the same as the bank/cash account.")
                return
            party_lines.append({
                "ledger_id": lid, "amount": amt,
                "narration": r["narr"].text().strip(),
            })

        if not party_lines:
            QMessageBox.warning(self, "Empty", "Add at least one party row.")
            return

        vdate = self.date_edit.date().toString("yyyy-MM-dd")
        narration = self.narration_edit.text().strip()
        reference = self.reference_edit.text().strip()

        try:
            if self.vtype == "PAYMENT":
                draft = self.engine.build_payment_multi(
                    vdate, bank_id, party_lines, narration, reference,
                )
            else:
                draft = self.engine.build_receipt_multi(
                    vdate, bank_id, party_lines, narration, reference,
                )
            posted = self.engine.post(draft)
        except Exception as e:
            QMessageBox.critical(self, "Post failed", str(e))
            return

        try:
            from core.license_manager import LicenseManager
            LicenseManager().record_transaction_posted("multi_party")
        except Exception:
            pass

        self.posted.emit(posted)
        QMessageBox.information(
            self, "Posted",
            f"✓  {posted.voucher_number}\n"
            f"₹{posted.total_amount:,.2f} across {len(party_lines)} parties",
        )
        self.accept()


class VoucherEntryPage(QWidget):
    voucher_posted = Signal(str, str, float)  # type, number, amount

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
        self._locked = False   # True when editing a bank-reconciled voucher:
        #                        date + amounts freeze, party + narration stay editable.
        self._edit_voucher_number: str = ""
        # Create-mode state — set via prefill_for_create() for posting from
        # other pages (Ledger Reconciliation etc.). on_post_callback runs
        # after a successful engine.post(), receiving the PostedVoucher.
        # Type selector stays visible — re-applies prefill on every switch.
        self._create_callback         = None
        self._create_banner_text: str = ""
        self._create_prefill          = None
        # Bill-wise allocation state (RECEIPT/PAYMENT). Set via the allocation
        # dialog; applied to the draft in _post. _alloc_for guards that the
        # stored allocations still match the current party + amount.
        self._pending_allocations: list = []
        self._alloc_for = None
        self._build_ui()
        self._wire_shortcuts()

    def _has_feature(self, feature: str) -> bool:
        try:
            from core.license_manager import LicenseManager
            return LicenseManager().has_feature(feature)
        except Exception:
            return False

    def _nudge_date(self, days: int):
        cur = self.date_edit.date()
        self.date_edit.setDate(cur.addDays(days))

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
        # 🗑 Delete — same soft-delete the Day Book toolbar offers, but
        # reachable from the edit view you're already on (which is where
        # users instinctively look for it after opening a voucher).
        self._delete_edit_btn = QPushButton("🗑  Delete voucher")
        self._delete_edit_btn.setFixedHeight(28)
        self._delete_edit_btn.setToolTip(
            "Cancel this voucher (soft-delete, reversible via audit log)"
        )
        self._delete_edit_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {THEME['danger']};
                border-radius: 5px;
                color: {THEME['danger']};
                padding: 0 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {THEME['danger']}22;
            }}
        """)
        self._delete_edit_btn.clicked.connect(self._delete_from_edit)
        eb.addWidget(self._delete_edit_btn)
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
            # Icon is part of the button text — rendered at the button's
            # font size. Bumped from 11→14 so the emoji is large enough
            # to read at a glance (was barely visible at 11). Height +4
            # to keep the text/icon comfortable inside the chip.
            btn = QPushButton(f"{icon}  {label}")
            btn.setCheckable(True)
            btn.setFixedHeight(38)
            colour = VOUCHER_COLOURS.get(vtype, THEME["accent"])
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {THEME['border']};
                    border-radius: 6px;
                    padding: 4px 12px;
                    font-size: 14px;
                    color: {THEME['text_secondary']};
                    min-height: 0;
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
        from ui.widgets import SmartDateEdit
        self.date_edit = SmartDateEdit(QDate.currentDate())
        self.date_edit.setFixedHeight(34)
        self.date_edit.setDisplayFormat(qt_format())

        # ±1 day steppers — paid (STANDARD+) shortcut for back-dated
        # voucher entry: type today's date once, then nudge a day at a time.
        # Styled flat/borderless so they read as date-field accessories,
        # not as standalone buttons that compete with Post / Clear.
        date_row = QHBoxLayout()
        date_row.setSpacing(2)
        date_row.setContentsMargins(0, 0, 0, 0)

        _arrow_qss = f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {THEME['border']};
                border-radius: 5px;
                color: {THEME['text_secondary']};
                padding: 0;
                font-size: 18px;
                font-weight: bold;
                min-width: 0;
            }}
            QPushButton:hover {{
                background: {THEME['bg_input']};
                border-color: {THEME['accent']};
                color: {THEME['accent']};
            }}
            QPushButton:pressed {{
                background: {THEME['accent_dim']};
            }}
        """
        self._date_prev_btn = QPushButton("‹")
        self._date_prev_btn.setFixedSize(36, 34)
        self._date_prev_btn.setStyleSheet(_arrow_qss)
        self._date_prev_btn.setToolTip("Previous day  (Alt+,)")
        self._date_prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._date_prev_btn.clicked.connect(lambda: self._nudge_date(-1))
        self._date_next_btn = QPushButton("›")
        self._date_next_btn.setFixedSize(36, 34)
        self._date_next_btn.setStyleSheet(_arrow_qss)
        self._date_next_btn.setToolTip("Next day  (Alt+.)")
        self._date_next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._date_next_btn.clicked.connect(lambda: self._nudge_date(+1))
        date_row.addWidget(self._date_prev_btn)
        date_row.addWidget(self.date_edit, 1)
        date_row.addWidget(self._date_next_btn)
        date_col.addLayout(date_row)

        # Hide the steppers for tiers that don't have the feature.
        if not self._has_feature("sticky_voucher_date"):
            self._date_prev_btn.setVisible(False)
            self._date_next_btn.setVisible(False)

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

        # AI fill — only shown for SALES / PURCHASE (toggled in _select_type).
        ai_col = QVBoxLayout()
        ai_col.setSpacing(3)
        ai_col.addWidget(make_label(" "))
        self._ai_fill_btn = QPushButton("🤖  AI fill from document…")
        self._ai_fill_btn.setFixedHeight(34)
        self._ai_fill_btn.setToolTip(
            "Pick an invoice / bill — AI reads it and fills this voucher "
            "for you to review before posting."
        )
        self._ai_fill_btn.clicked.connect(self._ai_fill_from_document)
        ai_col.addWidget(self._ai_fill_btn)
        meta_layout.addLayout(ai_col)

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

        # ── Multi-party row ──
        # Dedicated row so the button is impossible to miss on Payment /
        # Receipt vouchers when the feature is unlocked. Sits below the
        # GST/Total row inside the same card. Was previously crammed into
        # the Amount row's right edge where it slid off-screen on narrow
        # windows; the dedicated row fixes that.
        self._multi_party_btn = QPushButton(
            "+  Multi-party voucher  (one bank entry, several parties)"
        )
        self._multi_party_btn.setMinimumHeight(40)
        self._multi_party_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._multi_party_btn.setToolTip(
            "Open multi-party voucher: one bank entry, several parties.\n"
            "Use when a single bank transaction settles many parties at once "
            "(e.g. a payment gateway settlement covering N customers)."
        )
        self._multi_party_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['accent_dim']};
                border: 1.5px dashed {THEME['accent']};
                border-radius: 8px;
                color: {THEME['accent']};
                padding: 8px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {THEME['accent']}22;
                border-style: solid;
            }}
        """)
        self._multi_party_btn.clicked.connect(self._open_multi_party_dialog)
        inner.addWidget(self._multi_party_btn)

        # ── Bill-wise allocation row (RECEIPT/PAYMENT, PRO+) ──
        self._alloc_btn = QPushButton("🧾  Allocate to bills…  (Against Reference)")
        self._alloc_btn.setMinimumHeight(40)
        self._alloc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._alloc_btn.setToolTip(
            "Settle this receipt/payment against the party's specific open "
            "invoices (bill-by-bill). Anything not allocated posts on-account.")
        self._alloc_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['accent_dim']};
                border: 1.5px dashed {THEME['accent']};
                border-radius: 8px;
                color: {THEME['accent']};
                padding: 8px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {THEME['accent']}22;
                border-style: solid;
            }}
        """)
        self._alloc_btn.clicked.connect(self._open_alloc_dialog)
        self._alloc_btn.setVisible(False)
        inner.addWidget(self._alloc_btn)

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
        self._ai_fill_btn.setVisible(vtype in ("SALES", "PURCHASE"))
        self._multi_party_btn.setVisible(
            vtype in ("PAYMENT", "RECEIPT")
            and self._has_feature("multi_party_voucher")
        )
        # Bill-wise allocation — only for single receipt/payment on PRO+. The
        # stored allocations are party+amount specific, so reset on type switch.
        if hasattr(self, "_alloc_btn"):
            from core.user_prefs import prefs as _prefs
            self._alloc_btn.setVisible(
                vtype in ("PAYMENT", "RECEIPT")
                and self._has_feature("bill_wise_refs")
                and bool(_prefs.get("bill_wise_enabled", True))
            )
            self._reset_allocations()

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

    def _reset_allocations(self) -> None:
        self._pending_allocations = []
        self._alloc_for = None
        if hasattr(self, "_alloc_btn"):
            self._alloc_btn.setText("🧾  Allocate to bills…  (Against Reference)")

    def _open_alloc_dialog(self) -> None:
        party_id = self.field1_ledger.selected_id if self.field1_ledger else None
        amount = self.amount_edit.value()
        if not party_id:
            QMessageBox.warning(self, "Select a party",
                "Choose the party first, then allocate against their bills.")
            return
        if amount <= 0:
            QMessageBox.warning(self, "Enter an amount",
                "Enter the receipt/payment amount before allocating.")
            return
        try:
            from ui.bill_allocation_dialog import BillAllocationDialog
            party_name = (self.field1_ledger.text()
                          if hasattr(self.field1_ledger, "text") else "")
            dlg = BillAllocationDialog(
                self.engine.db, self.engine.company_id,
                party_id, party_name, amount, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._pending_allocations = dlg.allocations()
                self._alloc_for = (party_id, amount)
                n = sum(1 for a in self._pending_allocations if a.get("bill_ref_id"))
                tot = sum(a["amount"] for a in self._pending_allocations
                          if a.get("bill_ref_id"))
                if n:
                    self._alloc_btn.setText(
                        f"🧾  {n} bill(s) allocated · ₹{tot:,.2f}  (edit)")
                else:
                    self._alloc_btn.setText("🧾  On-account (no bill)  (edit)")
        except Exception as e:
            QMessageBox.critical(self, "Allocation error", str(e))

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

            # Bill-wise: attach allocations chosen in the dialog — applies to
            # BOTH create and edit. Guarded to the current party + amount so a
            # changed party/amount after filling the dialog is ignored.
            if (vtype in ("RECEIPT", "PAYMENT") and self._pending_allocations
                    and self._alloc_for == (self.field1_ledger.selected_id,
                                            self.amount_edit.value())):
                draft.allocations = self._pending_allocations

            if self._edit_voucher_id and self._locked:
                # LOCKED edit — re-point party ledgers + narration only; date
                # and amounts are frozen so the bank reconciliation holds.
                ledger_changes, line_notes = {}, {}
                for row in self._journal_rows:
                    lid = getattr(row, "_line_id", None)
                    if lid is None:
                        continue
                    line_notes[lid] = row.narration.text().strip()
                    if (not getattr(row, "_cleared", False)
                            and row.ledger_id
                            and row.ledger_id != getattr(row, "_orig_ledger_id", None)):
                        ledger_changes[lid] = row.ledger_id
                self.engine.update_voucher_constrained(
                    self._edit_voucher_id,
                    ledger_changes=ledger_changes,
                    narration=narration,
                    reference=reference,
                    line_narrations=line_notes,
                )
                QMessageBox.information(
                    self, "Updated",
                    f"✎  {self._edit_voucher_number} updated "
                    f"(party / details).\nDate & amount unchanged — "
                    f"reconciliation preserved.",
                )
                self._exit_edit_mode()
                self._clear()
                win = self.window()
                if hasattr(win, "return_from_voucher_edit"):
                    win.return_from_voucher_edit()
                return

            if self._edit_voucher_id:
                # EDIT mode — replace the existing voucher in place
                posted = self.engine.update_voucher(self._edit_voucher_id, draft)
                # Count the edit. Weight defaults to 0 in v1 so edits
                # are free, but the call site is wired so any future
                # pricing change in core/txn_weights.py automatically
                # applies without needing a code change here.
                try:
                    from core.license_manager import LicenseManager
                    LicenseManager().record_transaction_posted("edit")
                except Exception:
                    pass
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
                LicenseManager().record_transaction_posted("single_voucher")
            except Exception:
                pass

            # Success notification
            colour = VOUCHER_COLOURS.get(vtype, THEME["success"])
            self.voucher_posted.emit(posted.voucher_number, vtype, posted.total_amount)

            from core.user_prefs import prefs as _prefs
            if _prefs.get("after_post_toast", True):
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
            # No existing voucher in create-mode → nothing to delete.
            self._delete_edit_btn.setVisible(False)
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
        from PySide6.QtCore import QDate
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
        # Bank-reconciled lines no longer BLOCK editing — they lock date +
        # amount (constrained edit) while party + narration stay editable.
        self._locked = any((l.get("cleared_date") or "") for l in v["lines"])

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
        from PySide6.QtCore import QDate
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
            # Remember the original line so a constrained (locked) save can
            # re-point only the party ledgers without delete+reinsert.
            row._line_id        = line["id"]
            row._orig_ledger_id = line["ledger_id"]
            row._cleared        = bool((line.get("cleared_date") or ""))
        self._update_balance_journal()

        # Locked (bank-reconciled): freeze date + every amount/side, and freeze
        # the reconciled line's own ledger; leave party ledgers + narration open.
        if self._locked:
            self.date_edit.setEnabled(False)
            for row in self._journal_rows:
                row.amount_edit.setEnabled(False)
                row.type_toggle.setEnabled(False)
                if getattr(row, "_cleared", False):
                    row.ledger_search.setEnabled(False)

        # Show edit banner + relabel post button
        _lock_note = ("   🔒 Bank-reconciled — date & amount locked; "
                      "change party / details only") if self._locked else ""
        self._edit_banner_label.setText(
            f"✎ Editing  {v['voucher_number']}  ·  "
            f"{v['voucher_type'].replace('_',' ')}{_lock_note}"
        )
        self._edit_banner.setVisible(True)
        # Real voucher loaded — Delete is meaningful here.
        self._delete_edit_btn.setVisible(True)
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
        # Clear the reconciliation lock + re-enable the date field for the
        # next (create / unlocked) entry.
        self._locked = False
        self.date_edit.setEnabled(True)
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

    def _delete_from_edit(self):
        """Cancel-voucher action triggered from the edit banner. Mirrors the
        Day Book Delete handler so the cancellation has identical semantics
        (engine.cancel_voucher → is_cancelled=1, ledger impact reversed,
        audit row written) — just reachable from a different UI surface."""
        from PySide6.QtWidgets import QInputDialog
        vid = self._edit_voucher_id
        if not vid:
            return
        vno = self._edit_voucher_number or f"#{vid}"
        confirm = QMessageBox.question(
            self, "Cancel voucher?",
            f"Cancel voucher {vno}?\n\n"
            "This soft-deletes the voucher (preserves audit trail) and "
            "reverses its effect on every ledger it touched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        reason, ok = QInputDialog.getText(
            self, "Reason",
            "Reason for cancellation (optional, kept in audit log):",
        )
        if not ok:
            return
        try:
            self.engine.cancel_voucher(vid, reason=reason.strip())
        except Exception as e:
            QMessageBox.critical(self, "Cancel failed", str(e))
            return

        self._exit_edit_mode()
        self._clear()
        self._select_type("PAYMENT")
        win = self.window()
        if hasattr(win, "return_from_voucher_edit"):
            win.return_from_voucher_edit()

    def _clear(self):
        self.narration_edit.clear()
        self.reference_edit.clear()
        self.amount_edit.setValue(0)
        self._reset_allocations()
        try:
            self.field1_ledger.clear()
            self.field2_ledger.clear()
        except Exception:
            pass
        # Honor 'default_voucher_date' pref: "today" or "last_used". On
        # STANDARD+ the sticky-date feature flips the default to "last_used"
        # so the date persists across posts until the user changes it; FREE
        # keeps the old "today" reset.
        from core.user_prefs import prefs as _prefs
        _default = "last_used" if self._has_feature("sticky_voucher_date") else "today"
        if _prefs.get("default_voucher_date", _default) == "today":
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
        from PySide6.QtGui import QShortcut, QKeySequence
        from PySide6.QtCore import Qt
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
        # Date steppers — only wired when the feature is on. Keeps the
        # shortcut from silently nudging the date for FREE-tier users
        # who don't see the buttons.
        if self._has_feature("sticky_voucher_date"):
            sc_prev = QShortcut(QKeySequence("Alt+,"), self)
            sc_prev.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc_prev.activated.connect(lambda: self._nudge_date(-1))
            sc_next = QShortcut(QKeySequence("Alt+."), self)
            sc_next.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc_next.activated.connect(lambda: self._nudge_date(+1))

    def _show_calculator(self):
        btn_pos = self._post_btn.mapToGlobal(self._post_btn.rect().topLeft())
        self.calculator.move(btn_pos.x() - 270, btn_pos.y() - 360)
        self.calculator.show()
        self.calculator.raise_()

    def _open_multi_party_dialog(self):
        """Open the multi-party Payment/Receipt dialog. Carries over the
        current date and the bank/cash ledger from field2 so the user
        doesn't have to retype them."""
        vtype = self._current_type
        if vtype not in ("PAYMENT", "RECEIPT"):
            return
        if not self._has_feature("multi_party_voucher"):
            return
        default_bank_id = getattr(self.field2_ledger, "selected_id", None)
        dlg = _MultiPartyVoucherDialog(
            self.engine, self.tree, vtype,
            default_date=self._get_date_str(),
            default_bank_id=default_bank_id,
            party_ledgers=self._party_ledgers,
            bank_ledgers=self._bank_cash,
            calculator=self.calculator,
            parent=self,
        )

        def _on_posted(posted):
            self.voucher_posted.emit(posted.voucher_number, vtype, posted.total_amount)
            self._clear()

        dlg.posted.connect(_on_posted)
        dlg.exec()

    # ── In-context AI fill (Sales / Purchase) ─────────────────────────────────

    def _ai_fill_from_document(self):
        """Pick an invoice/bill, let AI read it, and populate this voucher
        for the user to review before posting. Sales/Purchase only."""
        vtype = self._current_type
        if vtype not in ("SALES", "PURCHASE"):
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Pick invoice / bill", "",
            "All supported (*.pdf *.xlsx *.xls *.csv *.jpg *.jpeg *.png *.docx *.txt)",
        )
        if not path:
            return

        feature  = "sales_ai_fill" if vtype == "SALES" else "purchase_ai_fill"
        doc_type = "sales_invoice" if vtype == "SALES" else "purchase_invoice"

        try:
            ledger_names = [l["name"] for l in self.tree.get_all_ledgers()]
        except Exception:
            ledger_names = []
        try:
            company = self.engine.get_company().get("name", "")
        except Exception:
            company = ""

        self._ai_fill_btn.setEnabled(False)
        self._ai_fill_btn.setText("🤖  Reading document…")

        self._ai_thread = _AiFillThread(
            path, doc_type, feature, ledger_names, company
        )
        self._ai_thread.done.connect(self._on_ai_fill_done)
        self._ai_thread.error.connect(self._on_ai_fill_error)
        self._ai_thread.start()

    def _reset_ai_fill_btn(self):
        self._ai_fill_btn.setEnabled(True)
        self._ai_fill_btn.setText("🤖  AI fill from document…")

    def _on_ai_fill_error(self, msg: str):
        self._reset_ai_fill_btn()
        QMessageBox.critical(self, "AI fill failed", msg)

    def _on_ai_fill_done(self, vouchers: list):
        self._reset_ai_fill_btn()
        if not vouchers:
            QMessageBox.information(
                self, "Nothing found",
                "AI couldn't find a transaction in that document. "
                "Try a clearer scan, or fill the voucher manually.",
            )
            return

        v     = vouchers[0]
        vtype = self._current_type
        cand  = [
            (v.get("dr_ledger") or "").replace(" (NEW)", "").strip(),
            (v.get("cr_ledger") or "").replace(" (NEW)", "").strip(),
        ]
        cand  = [c for c in cand if c]

        # The AI's Dr/Cr orientation is unreliable on invoices (extract_vouchers
        # is bank-statement shaped), so don't trust it. Classify each returned
        # ledger by what it actually IS: field1 = the income/expense account,
        # field2 = the party. A wrong orientation otherwise lands an income
        # ledger on the debit side and the engine rejects the post.
        party_names = {l["name"] for l in self._party_bank_cash}
        acct_src    = self._income_ledgers if vtype == "SALES" else self._expense_ledgers
        acct_names  = {l["name"] for l in acct_src}

        f1_name = next((c for c in cand if c in acct_names), "")
        f2_name = next((c for c in cand if c in party_names), "")
        # If only one side classified cleanly, the leftover fills the other.
        leftover = [c for c in cand if c not in (f1_name, f2_name)]
        if not f1_name and leftover:
            f1_name = leftover.pop(0)
        if not f2_name and leftover:
            f2_name = leftover.pop(0)

        try:
            if f1_name:
                self.field1_ledger.set_ledger(f1_name)
            if f2_name:
                self.field2_ledger.set_ledger(f2_name)
        except Exception:
            pass

        if v.get("date"):
            self.date_edit.setDate(QDate.fromString(v["date"], "yyyy-MM-dd"))
        if v.get("narration"):
            self.narration_edit.setText(v["narration"])
        if v.get("reference"):
            self.reference_edit.setText(v["reference"])
        try:
            amt = abs(float(v.get("amount") or 0))
            if amt > 0:
                self.amount_edit.setValue(amt)
        except Exception:
            pass

        self._update_balance_smart()

        extra = ""
        if len(vouchers) > 1:
            extra = (
                f"\n\n{len(vouchers)} transactions were found — filled the "
                "first. For bulk documents, use the AI Document Reader."
            )
        QMessageBox.information(
            self, "AI fill done",
            "Voucher filled from the document. Review every field — "
            "especially the ledger accounts and GST rate — then Post." + extra,
        )
