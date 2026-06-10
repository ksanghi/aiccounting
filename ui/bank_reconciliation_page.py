"""
Bank Reconciliation page UI.

Three steps:
    Step 1 - Setup    : pick bank ledger + period, drop a statement file
    Step 2 - Review   : 3 tabs (Matched | Unmatched stmt | Unmatched book)
    Step 3 - Summary  : balances + finalise
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QDateEdit, QComboBox, QLineEdit,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QTabWidget, QSizePolicy, QDialog,
    QFormLayout, QInputDialog, QMenu, QPlainTextEdit, QScrollArea,
)
from PySide6.QtCore import Qt, QDate, Signal, QThread
from PySide6.QtGui  import QColor

from ui.theme   import THEME
from core.date_format import qt_format, format_iso
from ui.widgets import FilteredLedgerSearchEdit, AmountEdit, SmartDateEdit
from core.bank_reconciliation import (
    BankReconciler,
    LocalParseFailed,
    AccountMismatch,
    AccountUnsetWithFileNumber,
    BankNameMismatch,
    UnverifiedStatement,
)
from core.voucher_engine import VoucherDraft, VoucherLine
from ui.table_utils import NumericTableItem, DateTableItem, make_sortable, populating


# ── Background worker for import + auto-match ────────────────────────────────

class _ImportThread(QThread):
    """
    Runs BankReconciler.import_statement in a worker thread and surfaces
    the specific exception types as dedicated signals so the UI can show
    the right dialog and re-fire with adjusted flags.
    """
    progress           = Signal(str)
    finished           = Signal(int, object)         # statement_id, AutoMatchResult
    local_failed       = Signal(str)                 # error message
    account_mismatch   = Signal(str, str)            # ledger_acct, file_acct
    account_unset      = Signal(str)                 # file_acct
    bank_name_mismatch = Signal(str, str)            # ledger_name, file_bank_name
    unverified         = Signal(str)                 # ledger_name
    error              = Signal(str)                 # generic fallback

    def __init__(
        self,
        reconciler: BankReconciler,
        bank_ledger_id: int,
        file_path: str,
        period_from: str,
        period_to: str,
        allow_ai: bool = False,
        api_key: str = "",
        confirm_account_population: bool = False,
        force_mismatch_override: bool = False,
        confirm_unverified: bool = False,
    ):
        super().__init__()
        self.reconciler     = reconciler
        self.bank_ledger_id = bank_ledger_id
        self.file_path      = file_path
        self.period_from    = period_from
        self.period_to      = period_to
        self.allow_ai       = allow_ai
        self.api_key        = api_key
        self.confirm_account_population = confirm_account_population
        self.force_mismatch_override    = force_mismatch_override
        self.confirm_unverified         = confirm_unverified

    def run(self):
        try:
            self.progress.emit(
                "Sending to AI…" if self.allow_ai else "Parsing locally…"
            )
            stmt_id = self.reconciler.import_statement(
                bank_ledger_id=self.bank_ledger_id,
                file_path=self.file_path,
                period_from=self.period_from,
                period_to=self.period_to,
                allow_ai=self.allow_ai,
                api_key=self.api_key,
                confirm_account_population=self.confirm_account_population,
                force_mismatch_override=self.force_mismatch_override,
                confirm_unverified=self.confirm_unverified,
            )
            self.progress.emit("Matching against ledger entries…")
            result = self.reconciler.auto_match(stmt_id)
            self.finished.emit(stmt_id, result)
        except LocalParseFailed as e:
            self.local_failed.emit(str(e))
        except AccountUnsetWithFileNumber as e:
            self.account_unset.emit(e.file_account)
        except AccountMismatch as e:
            self.account_mismatch.emit(e.ledger_account, e.file_account)
        except BankNameMismatch as e:
            self.bank_name_mismatch.emit(e.ledger_name, e.file_bank_name)
        except UnverifiedStatement as e:
            self.unverified.emit(e.ledger_name)
        except Exception as e:
            self.error.emit(str(e))


# ── "Create Voucher" inline modal ────────────────────────────────────────────

class _CreateVoucherDialog(QDialog):
    """
    Lightweight modal for creating a single PAYMENT or RECEIPT voucher
    from an unmatched statement line.
    """
    posted = Signal(int, object)   # statement_line_id, PostedVoucher

    def __init__(self, reconciler: BankReconciler, tree,
                 bank_ledger_id: int, bank_ledger_name: str,
                 stmt_line: dict, parent=None):
        super().__init__(parent)
        self.reconciler = reconciler
        self.tree       = tree
        self.bank_ledger_id   = bank_ledger_id
        self.bank_ledger_name = bank_ledger_name
        self.stmt_line  = stmt_line

        is_payment = stmt_line["sign"] == "DR"   # money out of bank
        self.voucher_type = "PAYMENT" if is_payment else "RECEIPT"

        self.setWindowTitle(f"Create {self.voucher_type} voucher")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        head = QLabel(
            f"<b>{self.voucher_type}</b>  ·  ₹ {stmt_line['amount']:,.2f}  "
            f"·  {stmt_line['txn_date']}"
        )
        head.setStyleSheet(f"color:{THEME['accent']}; font-size:14px;")
        layout.addWidget(head)

        if stmt_line.get("narration"):
            narr = QLabel(stmt_line["narration"])
            narr.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
            narr.setWordWrap(True)
            layout.addWidget(narr)

        form = QFormLayout()
        form.setSpacing(10)

        # Counter-ledger picker (everything except the bank itself)
        all_ledgers = [
            l for l in self.tree.get_all_ledgers()
            if l["id"] != bank_ledger_id
        ]
        self._counter = FilteredLedgerSearchEdit(
            tree, calculator=None,
            ledger_list=all_ledgers,
            placeholder=(
                "Expense / vendor account..."
                if is_payment else
                "Customer / income account..."
            ),
        )
        counter_label = (
            "Expense / Paid to" if is_payment else "Income / Received from"
        )
        form.addRow(counter_label, self._counter)

        # Suggest a contra ledger from past matched/created vouchers on
        # this bank ledger. Saves the user looking up the same expense
        # category repeatedly (e.g. every JIO debit → Telephone Expenses).
        try:
            suggestion = reconciler.suggest_contra_ledger(
                bank_ledger_id=bank_ledger_id,
                narration=stmt_line.get("narration", ""),
                reference=stmt_line.get("reference", ""),
            )
        except Exception:
            suggestion = None
        if suggestion:
            self._counter.search.setText(suggestion["ledger_name"])
            self._counter._selected_id = suggestion["ledger_id"]
            hits = suggestion["hits"]
            hint_text = (
                f"💡 Suggested from history: matched '{suggestion['matched_on']}' "
                f"in {hits} prior voucher{'s' if hits > 1 else ''}. "
                f"Change if not correct."
            )
            hint = QLabel(hint_text)
            hint.setStyleSheet(f"color:{THEME['success']}; font-size:10px;")
            hint.setWordWrap(True)
            form.addRow("", hint)

        bank_lbl = QLabel(bank_ledger_name)
        bank_lbl.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:11px; padding:6px 0;"
        )
        form.addRow(
            "Paid from" if is_payment else "Deposited to",
            bank_lbl,
        )

        self._narration = QLineEdit(stmt_line.get("narration", ""))
        self._narration.setFixedHeight(34)
        form.addRow("Narration", self._narration)

        self._reference = QLineEdit(stmt_line.get("reference", ""))
        self._reference.setFixedHeight(34)
        form.addRow("Reference", self._reference)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        post_btn = QPushButton(f"Post {self.voucher_type}")
        post_btn.setObjectName("btn_primary")
        post_btn.clicked.connect(self._post)
        btn_row.addWidget(cancel)
        btn_row.addWidget(post_btn)
        layout.addLayout(btn_row)

    def _post(self):
        counter_id = self._counter.selected_id
        if not counter_id:
            QMessageBox.warning(self, "Missing", "Please pick a counter-ledger.")
            return

        amount = float(self.stmt_line["amount"])
        is_payment = self.voucher_type == "PAYMENT"

        if is_payment:
            lines = [
                VoucherLine(ledger_id=counter_id,            dr_amount=amount),
                VoucherLine(ledger_id=self.bank_ledger_id,   cr_amount=amount),
            ]
        else:
            lines = [
                VoucherLine(ledger_id=self.bank_ledger_id,   dr_amount=amount),
                VoucherLine(ledger_id=counter_id,            cr_amount=amount),
            ]

        draft = VoucherDraft(
            voucher_type=self.voucher_type,
            voucher_date=self.stmt_line["txn_date"],
            lines=lines,
            narration=self._narration.text().strip(),
            reference=self._reference.text().strip(),
            source="MANUAL",
        )

        try:
            posted = self.reconciler.create_voucher_for_line(
                statement_line_id=self.stmt_line["id"],
                bank_ledger_id=self.bank_ledger_id,
                draft=draft,
            )
        except Exception as e:
            QMessageBox.critical(self, "Post failed", str(e))
            return

        self.posted.emit(self.stmt_line["id"], posted)
        self.accept()


# ── "Find candidate" picker ──────────────────────────────────────────────────

class _FindCandidateDialog(QDialog):
    """
    Find Candidate picker.

    Default mode: single-select — pick ONE book entry whose amount equals
    the statement amount (used by the auto-match candidate query, which
    already filters within ±₹1).

    Split mode (paid 'bank_reco_split' feature): multi-select — pick N book
    entries that SUM to the statement amount. Used when a bank settlement
    bundles several smaller payments/receipts under one bank line.
    """
    picked = Signal(int)        # legacy single-pick signal
    picked_many = Signal(list)  # list[int] — split-mode multi-pick

    def __init__(self, candidates: list[dict],
                 stmt_sign: str = "DR",
                 stmt_amount: float = 0.0,
                 split_mode: bool = False,
                 tolerance: float = 1.0,
                 parent=None):
        super().__init__(parent)
        self.split_mode  = split_mode
        self.stmt_sign   = stmt_sign
        self.stmt_amount = float(stmt_amount or 0)
        self.tolerance   = tolerance

        self.setWindowTitle(
            "Pick ledger entries that sum to the bank amount"
            if split_mode else
            "Find a matching ledger entry"
        )
        self.setMinimumWidth(680)
        self.setMinimumHeight(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        if not candidates:
            hint = (
                "No uncleared ledger entries on the matching side within "
                "the date window."
                if split_mode else
                "No uncleared ledger entries within ±7 days "
                "and ±₹1.00 of this statement line."
            )
            layout.addWidget(QLabel(hint))
            close = QPushButton("Close")
            close.clicked.connect(self.reject)
            layout.addWidget(close)
            return

        if split_mode:
            layout.addWidget(QLabel(
                f"<b>{len(candidates)}</b> candidate(s) on the matching side. "
                f"Tick the rows whose amounts together equal the bank line of "
                f"<b>Rs. {self.stmt_amount:,.2f}</b>. Use Ctrl+click for "
                f"multi-select."
            ))
        else:
            layout.addWidget(QLabel(
                f"{len(candidates)} candidate(s) found. "
                "Select one to mark as cleared:"
            ))

        self._table = QTableWidget(len(candidates), 5)
        self._table.setHorizontalHeaderLabels(
            ["Date", "Voucher #", "Type", "Narration", "Amount (Dr / Cr)"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        if split_mode:
            self._table.setSelectionMode(
                QAbstractItemView.SelectionMode.ExtendedSelection
            )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.verticalHeader().setDefaultSectionSize(40)
        self._row_to_id: dict[int, int] = {}
        self._row_to_amount: dict[int, float] = {}
        for r, c in enumerate(candidates):
            self._row_to_id[r] = c["id"]
            # Pull whichever side carries the amount opposite the stmt sign —
            # that's what gets summed in split mode.
            amt_val = (
                float(c["dr_amount"] or 0)
                if stmt_sign == "CR" else
                float(c["cr_amount"] or 0)
            )
            self._row_to_amount[r] = amt_val
            self._table.setItem(r, 0, DateTableItem(c["voucher_date"]))
            self._table.setItem(r, 1, QTableWidgetItem(c["voucher_number"] or ""))
            self._table.setItem(r, 2, QTableWidgetItem(c["voucher_type"]))
            self._table.setItem(r, 3, QTableWidgetItem(c.get("narration") or ""))
            amt = (
                f"Dr Rs. {c['dr_amount']:,.2f}"
                if c["dr_amount"] else
                f"Cr Rs. {c['cr_amount']:,.2f}"
            )
            self._table.setItem(r, 4, QTableWidgetItem(amt))
        # Enable sort AFTER populating so the inserts don't re-sort live.
        make_sortable(self._table)
        layout.addWidget(self._table)

        # Running-total bar — only shown in split mode.
        self._total_lbl = QLabel("")
        if split_mode:
            self._total_lbl.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:12px; "
                f"padding:6px 0;"
            )
            layout.addWidget(self._total_lbl)
            self._table.itemSelectionChanged.connect(self._refresh_total)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self._ok_btn = QPushButton("Match Selected")
        self._ok_btn.setObjectName("btn_primary")
        self._ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(cancel)
        btn_row.addWidget(self._ok_btn)
        layout.addLayout(btn_row)

        if split_mode:
            self._refresh_total()

    def _refresh_total(self):
        rows = self._table.selectionModel().selectedRows()
        picked_total = sum(self._row_to_amount[r.row()] for r in rows)
        diff = picked_total - self.stmt_amount
        n = len(rows)
        if n == 0:
            self._total_lbl.setText(
                f"Selected: 0 rows · target Rs. {self.stmt_amount:,.2f}"
            )
            self._ok_btn.setEnabled(False)
            return
        within = abs(diff) <= self.tolerance
        status = "matches ✓" if within else (
            f"short by Rs. {-diff:,.2f}" if diff < 0
            else f"over by Rs. {diff:,.2f}"
        )
        self._total_lbl.setText(
            f"Selected: {n} row(s) · sum Rs. {picked_total:,.2f} "
            f"vs target Rs. {self.stmt_amount:,.2f} — {status}"
        )
        self._total_lbl.setStyleSheet(
            f"color:{THEME['success'] if within else THEME['danger']}; "
            f"font-size:12px; font-weight:bold; padding:6px 0;"
        )
        self._ok_btn.setEnabled(within)

    def _on_ok(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "Pick one", "Select a candidate row first.")
            return
        if self.split_mode:
            vl_ids = [self._row_to_id[r.row()] for r in rows]
            self.picked_many.emit(vl_ids)
        else:
            vl_id = self._row_to_id[rows[0].row()]
            self.picked.emit(vl_id)
        self.accept()


# ── Bulk voucher creation ───────────────────────────────────────────────────

class _BulkCreateVoucherDialog(QDialog):
    """
    Pick ONE contra ledger; post one PAYMENT/RECEIPT voucher per selected
    statement line, all going to that ledger. Each voucher uses the
    line's own date / amount / narration. The line's sign (DR vs CR)
    decides which side the bank lands on per voucher.

    Suggestion: looks at the first selected line's narration via
    BankReconciler.suggest_contra_ledger() — if matches a past pattern,
    pre-fills the picker.
    """
    def __init__(self, reconciler, tree,
                 bank_ledger_id: int, bank_ledger_name: str,
                 stmt_line_ids: list[int], parent=None):
        super().__init__(parent)
        self.reconciler     = reconciler
        self.tree           = tree
        self.bank_ledger_id = bank_ledger_id
        self.stmt_line_ids  = stmt_line_ids

        self.setWindowTitle(f"Create {len(stmt_line_ids)} vouchers")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        head = QLabel(
            f"Posting <b>{len(stmt_line_ids)}</b> vouchers from the selected "
            f"bank statement lines. All will land on the same contra ledger."
        )
        head.setWordWrap(True)
        head.setStyleSheet(f"color:{THEME['accent']}; font-size:13px;")
        layout.addWidget(head)

        bank_lbl = QLabel(
            f"Bank ledger: <b>{bank_ledger_name}</b>"
        )
        bank_lbl.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
        layout.addWidget(bank_lbl)

        form = QFormLayout()
        form.setSpacing(10)

        # Counter-ledger picker — pre-filled from history if available.
        all_ledgers = [
            l for l in self.tree.get_all_ledgers()
            if l["id"] != bank_ledger_id
        ]
        self._counter = FilteredLedgerSearchEdit(
            tree, calculator=None,
            ledger_list=all_ledgers,
            placeholder="Expense / income / vendor / customer account...",
        )
        form.addRow("Counter ledger", self._counter)

        # Look up the first line's narration to compute a suggestion.
        first_narr, first_ref = "", ""
        if stmt_line_ids:
            row = self.reconciler.db.execute(
                "SELECT narration, reference FROM bank_statement_lines WHERE id=?",
                (stmt_line_ids[0],),
            ).fetchone()
            if row:
                first_narr = row["narration"] or ""
                first_ref  = row["reference"] or ""

        try:
            suggestion = self.reconciler.suggest_contra_ledger(
                bank_ledger_id=bank_ledger_id,
                narration=first_narr, reference=first_ref,
            )
        except Exception:
            suggestion = None
        if suggestion:
            self._counter.search.setText(suggestion["ledger_name"])
            self._counter._selected_id = suggestion["ledger_id"]
            hits = suggestion["hits"]
            hint = QLabel(
                f"💡 Suggested from history: matched "
                f"'{suggestion['matched_on']}' in {hits} prior voucher"
                f"{'s' if hits > 1 else ''}. Change if not correct."
            )
            hint.setStyleSheet(f"color:{THEME['success']}; font-size:10px;")
            hint.setWordWrap(True)
            form.addRow("", hint)

        self._narration = QLineEdit()
        self._narration.setFixedHeight(34)
        self._narration.setPlaceholderText(
            "Optional — prefixed to each voucher's narration"
        )
        form.addRow("Narration prefix", self._narration)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        post_btn = QPushButton(f"Post {len(stmt_line_ids)} vouchers")
        post_btn.setObjectName("btn_primary")
        post_btn.clicked.connect(self._post)
        btn_row.addWidget(cancel)
        btn_row.addWidget(post_btn)
        layout.addLayout(btn_row)

    def _post(self):
        contra_id = self._counter.selected_id
        if not contra_id:
            QMessageBox.warning(self, "Missing", "Please pick a counter ledger.")
            return
        try:
            result = self.reconciler.bulk_create_simple_vouchers(
                statement_line_ids=self.stmt_line_ids,
                bank_ledger_id=self.bank_ledger_id,
                contra_ledger_id=contra_id,
                narration_prefix=self._narration.text().strip(),
            )
        except Exception as e:
            QMessageBox.critical(self, "Bulk post failed", str(e))
            return
        posted = result.get("posted", 0)
        errors = result.get("errors", [])
        # Count each bulk-posted voucher toward the license txn counter.
        # One disk write — record_transaction_posted handles the multiplier.
        if posted > 0:
            try:
                from core.license_manager import LicenseManager
                LicenseManager().record_transaction_posted(
                    "bank_reco", count=posted,
                )
            except Exception:
                pass
        msg = f"Posted {posted} voucher(s)."
        if errors:
            msg += f"\n\n{len(errors)} line(s) failed:\n  • " + "\n  • ".join(errors[:8])
            if len(errors) > 8:
                msg += f"\n  … and {len(errors) - 8} more"
        QMessageBox.information(self, "Bulk post", msg)
        self.accept()


# ── Main page ────────────────────────────────────────────────────────────────

class BankReconciliationPage(QWidget):
    """Constructor: (db, company_id, tree, voucher_engine, calculator, license_mgr)."""

    def __init__(self, db, company_id, tree, voucher_engine, calculator,
                 license_mgr, parent=None):
        super().__init__(parent)
        self.db             = db
        self.company_id     = company_id
        self.tree           = tree
        self.engine         = voucher_engine
        self.calculator     = calculator
        self.license_mgr    = license_mgr
        self.reconciler     = BankReconciler(db, company_id, tree)

        # Session state
        self._statement_id: int | None = None
        self._bank_ledger_id: int | None = None
        self._bank_ledger_name: str = ""
        self._period_from: str = ""
        self._period_to: str = ""
        self._pending_file_path: str = ""
        # Avoid re-prompting "Resume reconciliation?" every time the user
        # touches the ledger picker — fire once per bank-ledger selection.
        self._last_resume_prompt_for: int | None = None

        self._import_thread: _ImportThread | None = None

        self._build_ui()

    # ── UI scaffolding ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 0, 24, 24)
        root.setSpacing(0)

        title = QLabel("Bank Reconciliation")
        title.setObjectName("page_title")
        root.addWidget(title)
        sub = QLabel("Match imported bank statements to your ledger entries.")
        sub.setObjectName("page_subtitle")
        root.addWidget(sub)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        self._setup_page  = self._build_setup_page()
        self._review_page = self._build_review_page()
        self._summary_page = self._build_summary_page()
        self._stack.addWidget(self._setup_page)
        self._stack.addWidget(self._review_page)
        self._stack.addWidget(self._summary_page)

    # ── Step 1: Setup ─────────────────────────────────────────────────────────

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # Bank ledger + period
        card = QFrame()
        card.setObjectName("card")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(20, 20, 20, 20)
        card_lay.setSpacing(14)

        # Bank picker
        bank_row = QHBoxLayout()
        bank_lbl = QLabel("Bank Ledger")
        bank_lbl.setFixedWidth(150)
        bank_lbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        bank_row.addWidget(bank_lbl)

        bank_ledgers = [
            l for l in self.tree.get_bank_cash_ledgers()
            if l.get("is_bank")
        ]
        # Restrict the F2 quick-add (and F3 edit) to the Bank Accounts group
        # so a new ledger created from this picker is always a bank ledger
        # with the bank fields (account number / IFSC / bank name) shown.
        bank_group_rows = self.db.execute(
            "SELECT id FROM account_groups "
            " WHERE company_id=? AND lower(name)='bank accounts'",
            (self.company_id,),
        ).fetchall()
        bank_group_ids = [r["id"] for r in bank_group_rows]

        self._bank_picker = FilteredLedgerSearchEdit(
            self.tree, calculator=None,
            ledger_list=bank_ledgers,
            allowed_group_ids=bank_group_ids,
            placeholder="Choose a bank account…",
        )
        self._bank_picker.ledger_selected.connect(self._on_bank_picked)
        bank_row.addWidget(self._bank_picker, 1)
        card_lay.addLayout(bank_row)

        # Period
        period_row = QHBoxLayout()
        plbl = QLabel("Statement Period")
        plbl.setFixedWidth(150)
        plbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        period_row.addWidget(plbl)

        today = QDate.currentDate()
        fy_start = QDate(today.year() if today.month() >= 4 else today.year() - 1,
                         4, 1)
        self._period_from_edit = SmartDateEdit(fy_start)
        self._period_from_edit.setDisplayFormat(qt_format())
        self._period_from_edit.setFixedHeight(36)
        period_row.addWidget(self._period_from_edit)

        period_row.addWidget(QLabel("→"))

        self._period_to_edit = SmartDateEdit(today)
        self._period_to_edit.setDisplayFormat(qt_format())
        self._period_to_edit.setFixedHeight(36)
        period_row.addWidget(self._period_to_edit)
        period_row.addStretch()
        card_lay.addLayout(period_row)
        layout.addWidget(card)

        # Drop zone (lazy-imported here to avoid circulars at startup)
        from ui.document_reader_page import DropZone, _load_cfg, _save_cfg
        self._load_cfg = _load_cfg
        self._save_cfg = _save_cfg

        drop_card = QFrame()
        drop_card.setObjectName("card")
        drop_lay = QVBoxLayout(drop_card)
        drop_lay.setContentsMargins(20, 20, 20, 20)
        drop_lay.setSpacing(10)

        drop_title = QLabel("Statement file")
        drop_title.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        drop_lay.addWidget(drop_title)

        # Tier hint
        has_ai = self.license_mgr.has_feature("ai_document_reader")
        if has_ai:
            tier_hint = QLabel(
                "Local parser handles CSV / Excel / text-PDF for free. "
                "If a file can't be parsed locally (scanned PDFs, unusual "
                "layouts), you'll be offered the AI parser (Claude — uses "
                "credits)."
            )
        else:
            tier_hint = QLabel(
                "Local parser handles CSV / Excel / text-PDF for free. "
                "Scanned or unusual files would need the AI parser, "
                "which is on the PRO plan."
            )
        tier_hint.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:10px;"
        )
        tier_hint.setWordWrap(True)
        drop_lay.addWidget(tier_hint)

        self._drop = DropZone()
        self._drop.file_dropped.connect(self._on_file_dropped)
        drop_lay.addWidget(self._drop)

        # Legacy api_key field removed in Phase 2a — AI Routing dialog
        # (Settings → AI Routing, or auto-popped on first AI use) is the
        # single entry point now. We keep an invisible QLineEdit only so
        # the _fire_import path can still read .text() == "" safely.
        from PySide6.QtWidgets import QLineEdit as _QLE
        self._api_key_edit = _QLE()
        self._api_key_edit.setVisible(False)
        self._api_row = QWidget()
        self._api_row.setVisible(False)

        # Status / error label
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        self._status_lbl.setWordWrap(True)
        drop_lay.addWidget(self._status_lbl)

        layout.addWidget(drop_card)

        # Imported statements (un-finalised + finalised) with delete action
        imp_card = QFrame()
        imp_card.setObjectName("card")
        imp_lay = QVBoxLayout(imp_card)
        imp_lay.setContentsMargins(20, 16, 20, 16)
        imp_lay.setSpacing(8)
        imp_title = QLabel("Imported statements for this bank")
        imp_title.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        imp_lay.addWidget(imp_title)
        self._imports_table = QTableWidget(0, 6)
        self._imports_table.setHorizontalHeaderLabels(
            ["File", "Period", "Method", "Lines (m / u / o)", "Status", ""]
        )
        self._imports_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        h = self._imports_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, w in ((1, 180), (2, 70), (3, 130), (4, 100), (5, 100)):
            h.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self._imports_table.setColumnWidth(col, w)
        self._imports_table.verticalHeader().setDefaultSectionSize(44)
        self._imports_table.setMinimumHeight(120)
        make_sortable(self._imports_table)
        imp_lay.addWidget(self._imports_table)
        layout.addWidget(imp_card)

        # History
        hist_card = QFrame()
        hist_card.setObjectName("card")
        hist_lay = QVBoxLayout(hist_card)
        hist_lay.setContentsMargins(20, 16, 20, 16)
        hist_lay.setSpacing(8)

        hist_title = QLabel("Past reconciliations for this bank")
        hist_title.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        hist_lay.addWidget(hist_title)
        self._history_table = QTableWidget(0, 5)
        self._history_table.setHorizontalHeaderLabels(
            ["As of", "Book bal.", "Stmt bal.", "Matched / Unmatched (s/b)", "Finalised"]
        )
        self._history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._history_table.verticalHeader().setDefaultSectionSize(40)
        self._history_table.setMinimumHeight(120)
        make_sortable(self._history_table)
        hist_lay.addWidget(self._history_table)
        layout.addWidget(hist_card)

        layout.addStretch()

        # Wrap in a scroll area — the setup page stacks four cards
        # (bank+period, file drop, imported statements, past
        # reconciliations). On a shorter window the QStackedWidget
        # squeezed the lower cards below their minimum and the imports +
        # history tables collapsed to just their headers. A scroll area
        # gives every card its full height and scrolls instead.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(page)
        return scroll

    def _on_bank_picked(self, ledger_id, name, _row):
        # Reset the auto-prompt guard so changing ledger re-checks for an
        # in-progress reconciliation on the newly-picked one.
        if self._bank_ledger_id != ledger_id:
            self._last_resume_prompt_for = None
        self._bank_ledger_id = ledger_id
        self._bank_ledger_name = name
        self._refresh_history()
        self._auto_fill_period()

    def _on_resume_statement(self, statement_id: int, summary: dict | None = None):
        """
        Load a previously-imported (but not yet finalised) statement and
        jump straight to the Review step. The user can pick up exactly
        where they left off — every line's match_status / matched_voucher
        / ignored note was persisted as they worked, so the 100-rows-done
        state is already there in the DB.
        """
        stmt = self.reconciler.get_statement(statement_id)
        if not stmt:
            QMessageBox.warning(self, "Cannot resume",
                                "That statement is no longer in the database.")
            return
        self._statement_id = statement_id
        # Restore period bounds from the stored statement so the
        # Unmatched-Book query covers the right range.
        self._period_from = stmt.get("period_from") or ""
        self._period_to   = stmt.get("period_to")   or ""
        try:
            qfrom = QDate.fromString(self._period_from, "yyyy-MM-dd")
            qto   = QDate.fromString(self._period_to,   "yyyy-MM-dd")
            if qfrom.isValid():
                self._period_from_edit.setDate(qfrom)
            if qto.isValid():
                self._period_to_edit.setDate(qto)
        except Exception:
            pass
        self._populate_review()
        self._stack.setCurrentWidget(self._review_page)

    def _auto_fill_period(self):
        """
        Default the period to (last cleared date + 1 day) → today. If the
        bank has never been reconciled, fall back to FY-start → today
        (the original default).
        """
        from datetime import date, timedelta
        if not self._bank_ledger_id:
            return
        last = self.reconciler.last_cleared_date(self._bank_ledger_id)
        today = QDate.currentDate()
        if last:
            try:
                start = date.fromisoformat(last) + timedelta(days=1)
                qstart = QDate(start.year, start.month, start.day)
            except ValueError:
                qstart = self._period_from_edit.date()
        else:
            # FY start (April 1 of current Indian FY)
            y = today.year() if today.month() >= 4 else today.year() - 1
            qstart = QDate(y, 4, 1)
        self._period_from_edit.setDate(qstart)
        self._period_to_edit.setDate(today)

    def _refresh_history(self):
        self._history_table.setRowCount(0)
        self._imports_table.setRowCount(0)
        if not self._bank_ledger_id:
            return

        # Disable sort while bulk-populating — otherwise each setItem
        # re-sorts and the row indexes we're writing into stop matching.
        self._imports_table.setSortingEnabled(False)
        self._history_table.setSortingEnabled(False)

        # Imported statements
        imports = self.reconciler.recent_imports(self._bank_ledger_id)
        self._imports_table.setRowCount(len(imports))
        active_to_resume: dict | None = None  # for the auto-prompt below
        for r, row in enumerate(imports):
            self._imports_table.setItem(r, 0, QTableWidgetItem(row["file_name"]))
            self._imports_table.setItem(r, 1, QTableWidgetItem(
                f"{row['period_from']}  →  {row['period_to']}"
            ))
            self._imports_table.setItem(r, 2, QTableWidgetItem(row["import_method"]))
            self._imports_table.setItem(r, 3, QTableWidgetItem(
                f"{row['matched']} / {row['unmatched']} / {row['resolved_other']}"
            ))
            in_progress = not row["finalised"]
            status_text = "In progress" if in_progress else "Finalised"
            status_item = QTableWidgetItem(status_text)
            if in_progress:
                status_item.setForeground(QColor(THEME["warning"]))
            self._imports_table.setItem(r, 4, status_item)

            cell = QWidget()
            ch = QHBoxLayout(cell)
            ch.setContentsMargins(6, 0, 6, 0)
            ch.setSpacing(4)

            if in_progress:
                resume_btn = self._compact_btn("Resume ▸")
                resume_btn.setStyleSheet(
                    f"QPushButton {{ background:{THEME['accent']}; "
                    f"color:white; border:none; border-radius:5px; "
                    f"padding:0px 10px; font-size:11px; font-weight:bold; "
                    f"min-height:0; }}"
                    f"QPushButton:hover {{ background:{THEME['accent_hover']}; }}"
                )
                resume_btn.clicked.connect(
                    lambda _, sid=row["id"], summary=row:
                        self._on_resume_statement(sid, summary)
                )
                ch.addWidget(resume_btn)
                # Remember the most recent (= first row, sorted DESC) so we
                # can auto-prompt below.
                if active_to_resume is None:
                    active_to_resume = dict(row)

            del_btn = self._compact_btn("Delete")
            del_btn.clicked.connect(
                lambda _, sid=row["id"], summary=row: self._on_delete_statement(sid, summary)
            )
            ch.addWidget(del_btn)
            ch.addStretch()
            self._imports_table.setCellWidget(r, 5, cell)

        # Auto-prompt: if there's any in-progress import for this bank
        # ledger, ask the user whether to resume. This is what the user
        # asked for — they shouldn't have to know about the Imports
        # table to recover an interrupted reconciliation. Only fires once
        # per bank-picker selection, not on every refresh.
        if (active_to_resume is not None
                and self._bank_ledger_id != self._last_resume_prompt_for):
            self._last_resume_prompt_for = self._bank_ledger_id
            done = (active_to_resume.get("matched") or 0) + (active_to_resume.get("resolved_other") or 0)
            total = active_to_resume.get("total_lines") or 0
            box = QMessageBox(self)
            box.setWindowTitle("Resume reconciliation?")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(
                f"You have an in-progress reconciliation for "
                f"<b>{self._bank_ledger_name}</b>."
            )
            box.setInformativeText(
                f"File: <i>{active_to_resume.get('file_name','')}</i><br>"
                f"Period: {active_to_resume.get('period_from','')} → "
                f"{active_to_resume.get('period_to','')}<br>"
                f"<b>{done}</b> of <b>{total}</b> lines already done."
            )
            resume_b = box.addButton("Resume ▸", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Start fresh", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is resume_b:
                self._on_resume_statement(active_to_resume["id"], active_to_resume)

        # Past reconciliations
        rows = self.reconciler.history_for_ledger(self._bank_ledger_id)
        self._history_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self._history_table.setItem(r, 0, DateTableItem(row["as_of_date"]))
            self._history_table.setItem(r, 1, NumericTableItem(
                f"₹ {row['book_balance']:,.2f}", row["book_balance"]
            ))
            self._history_table.setItem(r, 2, NumericTableItem(
                f"₹ {row['statement_balance']:,.2f}", row["statement_balance"]
            ))
            self._history_table.setItem(r, 3, QTableWidgetItem(
                f"{row['matched_count']}  /  "
                f"{row['unmatched_stmt_count']} s · {row['unmatched_book_count']} b"
            ))
            self._history_table.setItem(r, 4, QTableWidgetItem(
                row["finalised_at"][:16]
            ))

        self._imports_table.setSortingEnabled(True)
        self._history_table.setSortingEnabled(True)

    def _on_delete_statement(self, statement_id: int, summary: dict):
        matched = summary.get("matched") or 0
        warn = ""
        if matched:
            warn = (
                f"\n\nThis statement has {matched} matched line(s). "
                "Deleting it will reset the cleared-date on those "
                "voucher lines (the vouchers themselves are kept)."
            )
        reply = QMessageBox.question(
            self,
            "Delete statement?",
            f"Delete '{summary.get('file_name')}' "
            f"({summary.get('period_from')} → {summary.get('period_to')})?"
            f"{warn}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.reconciler.delete_statement(statement_id)
        except Exception as e:
            QMessageBox.critical(self, "Delete failed", str(e))
            return
        self._refresh_history()

    def _on_file_dropped(self, path: str):
        if not self._bank_ledger_id:
            QMessageBox.warning(
                self, "Pick a bank first",
                "Select a bank ledger before importing a statement.",
            )
            return

        # Always remember the file path so we can re-fire after the user
        # responds to a dialog (try AI / set ledger account / override mismatch).
        self._pending_file_path = path
        self._period_from = self._period_from_edit.date().toString("yyyy-MM-dd")
        self._period_to   = self._period_to_edit.date().toString("yyyy-MM-dd")

        self._fire_import(allow_ai=False)

    def _fire_import(
        self,
        *,
        allow_ai: bool = False,
        confirm_account_population: bool = False,
        force_mismatch_override: bool = False,
        confirm_unverified: bool = False,
    ):
        """Spawn the import worker. Re-callable with adjusted flags."""
        api_key = ""
        if allow_ai:
            if not self.license_mgr.has_feature("ai_document_reader"):
                QMessageBox.information(
                    self, "PRO required",
                    "The AI parser requires the PRO plan. "
                    "Local parsing is included in your current plan; "
                    "ensure your file is a CSV/Excel/text-PDF, or upgrade.",
                )
                return
            # No routing prompt — `bank_statement_ai` is an ag_key feature
            # (config/ai_features.json), so it routes automatically: the
            # customer's own key if they have one, otherwise the AccGenie
            # wallet via /ai/proxy. Any routing failure surfaces from the
            # import thread's error signal.

        self._status_lbl.setText(
            "Sending to AI…" if allow_ai else "Parsing locally…"
        )
        self._import_thread = _ImportThread(
            self.reconciler,
            self._bank_ledger_id,
            self._pending_file_path,
            period_from=self._period_from,
            period_to=self._period_to,
            allow_ai=allow_ai,
            api_key=api_key,
            confirm_account_population=confirm_account_population,
            force_mismatch_override=force_mismatch_override,
            confirm_unverified=confirm_unverified,
        )
        self._import_thread.progress.connect(self._status_lbl.setText)
        self._import_thread.finished.connect(self._on_import_done)
        self._import_thread.local_failed.connect(self._on_local_failed)
        self._import_thread.account_unset.connect(self._on_account_unset)
        self._import_thread.account_mismatch.connect(self._on_account_mismatch)
        self._import_thread.bank_name_mismatch.connect(self._on_bank_name_mismatch)
        self._import_thread.unverified.connect(self._on_unverified)
        self._import_thread.error.connect(self._on_import_error)
        self._import_thread.start()

    def _on_local_failed(self, error_msg: str):
        """Local parser couldn't read the file — offer the AI fallback."""
        self._status_lbl.setText("")
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Local parse failed")
        msg.setText("The file couldn't be parsed locally.")
        msg.setInformativeText(
            f"{error_msg}\n\n"
            "You can either upload a different file (a CSV / Excel export "
            "usually works) or use the paid AI parser.\n\n"
            "AI parsing uses Claude credits — roughly Rs.0.10 per text page "
            "and Rs.5 per scanned page."
        )
        try_ai = msg.addButton("Try AI parser", QMessageBox.ButtonRole.AcceptRole)
        cancel = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is try_ai:
            self._fire_import(allow_ai=True)

    def _on_account_unset(self, file_account: str):
        """File has an account #; ledger has none. Offer to populate."""
        self._status_lbl.setText("")
        reply = QMessageBox.question(
            self,
            "Set ledger account number?",
            f"This statement is for account {file_account}.\n\n"
            f"The ledger \"{self._bank_ledger_name}\" doesn't have an "
            "account number set yet. Set it now and continue importing?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._fire_import(confirm_account_population=True)

    def _on_account_mismatch(self, ledger_account: str, file_account: str):
        """Account on file ≠ account on ledger. Block and let the user decide."""
        self._status_lbl.setText("")
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Account number mismatch")
        msg.setText("This statement is for a different account.")
        msg.setInformativeText(
            f"Ledger \"{self._bank_ledger_name}\" account: {ledger_account}\n"
            f"Statement file account: {file_account}\n\n"
            "Either correct the account number on the ledger / pick a "
            "different ledger, or import a different statement file."
        )
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

    def _on_bank_name_mismatch(self, ledger_name: str, file_bank_name: str):
        """File bank name doesn't match the ledger; no account # to fall back on."""
        self._status_lbl.setText("")
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Different bank?")
        msg.setText("This statement looks like it's from a different bank.")
        msg.setInformativeText(
            f"Ledger: {ledger_name}\n"
            f"Statement says: {file_bank_name}\n\n"
            "The file has no account number to verify against. Continue "
            "importing anyway, or pick a different ledger / file?"
        )
        proceed = msg.addButton("Import anyway", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is proceed:
            self._fire_import(force_mismatch_override=True, confirm_unverified=True)

    def _on_unverified(self, ledger_name: str):
        """Couldn't detect bank or account from file — soft confirm."""
        self._status_lbl.setText("")
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Couldn't verify ownership")
        msg.setText("This statement file doesn't show a bank name or account number.")
        msg.setInformativeText(
            f"Are you sure it's for ledger \"{ledger_name}\"?"
        )
        proceed = msg.addButton("Yes, import it", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is proceed:
            self._fire_import(confirm_unverified=True)

    def _on_import_done(self, statement_id: int, result):
        self._statement_id = statement_id
        ambig = getattr(result, "ambiguous_skipped", 0)
        msg = (
            f"Imported. Matched {result.matched}, "
            f"{result.unmatched_stmt} stmt unmatched, "
            f"{result.unmatched_book} book unmatched."
        )
        if ambig:
            # Conservative auto-match leaves same-(date,amount,sign) ties
            # for the user. Surface the count so they know there's work to
            # do on the Unmatched tab and aren't surprised by the lower
            # matched count vs. older builds.
            msg += f" {ambig} ambiguous — left for manual review."
        self._status_lbl.setText(msg)
        self._populate_review()
        self._stack.setCurrentWidget(self._review_page)

    def _on_import_error(self, msg: str):
        self._status_lbl.setText("")
        QMessageBox.critical(self, "Import failed", msg)

    # ── Step 2: Review ────────────────────────────────────────────────────────

    def _build_review_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ── Bento KPI strip — at-a-glance reco state ─────────────────
        # Replaces the cramped one-line "  ✓ 47 matched | ⚠ 23 ..."
        # summary with 4 status-coloured tiles. Heights tuned so the
        # tables below still get most of the vertical real estate on
        # a 750-line statement.
        try:
            from ui.bento_widgets import KPITile
            kpi_row = QHBoxLayout()
            kpi_row.setSpacing(12)
            self._kpi_matched   = KPITile("Matched", "0", "", status="good")
            self._kpi_unmatched = KPITile("Unmatched · stmt", "0", "", status="warn")
            self._kpi_book      = KPITile("Unmatched · book", "0", "", status="warn")
            self._kpi_ignored   = KPITile("Ignored", "0", "", status="")
            for t in (self._kpi_matched, self._kpi_unmatched,
                      self._kpi_book, self._kpi_ignored):
                t.setMaximumHeight(82)
                kpi_row.addWidget(t, 1)
            layout.addLayout(kpi_row)
        except Exception:
            # Fallback: skip the bento row if widgets aren't on path.
            self._kpi_matched = None
            self._kpi_unmatched = None
            self._kpi_book = None
            self._kpi_ignored = None

        # Compact top bar — 26px tall so the tables get the rest of the
        # window. On a 750-line statement every pixel of vertical space
        # spent on chrome is one less row visible.
        bar = QHBoxLayout()
        bar.setSpacing(8)
        back_btn = QPushButton("← Setup")
        back_btn.setFixedHeight(26)
        back_btn.clicked.connect(
            lambda: self._stack.setCurrentWidget(self._setup_page)
        )
        bar.addWidget(back_btn)

        self._review_summary = QLabel("")
        self._review_summary.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        bar.addWidget(self._review_summary, 1)

        next_btn = QPushButton("Continue to Summary →")
        next_btn.setObjectName("btn_primary")
        next_btn.setFixedHeight(26)
        next_btn.clicked.connect(self._go_to_summary)
        bar.addWidget(next_btn)
        layout.addLayout(bar)

        self._tabs = QTabWidget()
        self._matched_table = self._make_table(
            ["Date", "Sign", "Amount", "Voucher #", "Type", "Narration", ""],
            [110, 60, 120, 130, 90, 0, 110],
        )
        self._unmatched_stmt_table = self._make_table(
            ["Date", "Sign", "Amount", "Narration", "Reference", "Status", ""],
            [110, 60, 120, 0, 130, 110, 320],
        )
        # Multi-row select so the user can ctrl/shift-click a batch of
        # lines (e.g. every JIO debit) and act on them in one go.
        self._unmatched_stmt_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._unmatched_book_table = self._make_table(
            ["Date", "Voucher #", "Type", "Amount", "Narration", ""],
            [110, 130, 90, 130, 0, 140],
        )
        self._ignored_table = self._make_table(
            ["Date", "Sign", "Amount", "Narration", "Reference", "Note", ""],
            [110, 60, 120, 0, 130, 0, 130],
        )

        # Single thin toolbar above the Unmatched Statement table: filter
        # input on the left, selection summary + bulk-action buttons on
        # the right (buttons hidden until something is selected). All
        # ~28px tall to maximise the room left for actual data rows on a
        # 700-row statement.
        unmatched_wrap = QWidget()
        uw_layout = QVBoxLayout(unmatched_wrap)
        uw_layout.setContentsMargins(0, 0, 0, 0)
        uw_layout.setSpacing(4)

        bar = QHBoxLayout()
        bar.setContentsMargins(2, 2, 2, 2)
        bar.setSpacing(6)

        self._stmt_filter = QLineEdit()
        self._stmt_filter.setPlaceholderText(
            "🔍 Filter narration / reference — e.g. JIO, AMAZON…"
        )
        self._stmt_filter.setFixedHeight(28)
        self._stmt_filter.setClearButtonEnabled(True)
        self._stmt_filter.textChanged.connect(self._apply_stmt_filter)
        bar.addWidget(self._stmt_filter, 3)

        # "Select all visible" — typing JIO then clicking this is the
        # 3-click workflow for the user's 750-row batch.
        self._select_all_visible_btn = QPushButton("Select all visible")
        self._select_all_visible_btn.setFixedHeight(28)
        self._select_all_visible_btn.clicked.connect(self._select_all_visible_stmt_rows)
        bar.addWidget(self._select_all_visible_btn)

        self._bulk_label = QLabel("")
        self._bulk_label.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        bar.addWidget(self._bulk_label)

        self._bulk_voucher_btn = QPushButton("Create vouchers for selected →")
        self._bulk_voucher_btn.setFixedHeight(28)
        self._bulk_voucher_btn.setVisible(False)
        self._bulk_voucher_btn.clicked.connect(self._on_bulk_create_voucher)
        bar.addWidget(self._bulk_voucher_btn)
        self._bulk_ignore_btn = QPushButton("Ignore selected")
        self._bulk_ignore_btn.setFixedHeight(28)
        self._bulk_ignore_btn.setVisible(False)
        self._bulk_ignore_btn.clicked.connect(self._on_bulk_ignore)
        bar.addWidget(self._bulk_ignore_btn)

        uw_layout.addLayout(bar)
        uw_layout.addWidget(self._unmatched_stmt_table)

        # Toggle the bulk buttons whenever the selection changes.
        self._unmatched_stmt_table.itemSelectionChanged.connect(
            self._refresh_bulk_buttons
        )

        # Matched tab: thin toolbar with "Undo auto-matches" so a polluted
        # auto-match pass can be wiped in one click without touching the
        # user's manual / voucher_created resolutions.
        matched_wrap = QWidget()
        mw_layout = QVBoxLayout(matched_wrap)
        mw_layout.setContentsMargins(0, 0, 0, 0)
        mw_layout.setSpacing(4)
        m_bar = QHBoxLayout()
        m_bar.setContentsMargins(2, 2, 2, 2)
        m_bar.setSpacing(6)
        m_bar.addStretch(1)
        self._undo_auto_btn = QPushButton("Undo all auto-matches")
        self._undo_auto_btn.setFixedHeight(28)
        self._undo_auto_btn.setToolTip(
            "Reverts every auto-matched row on this statement back to "
            "Unmatched. Leaves your manual matches and created vouchers "
            "alone."
        )
        self._undo_auto_btn.clicked.connect(self._on_undo_auto_matches)
        m_bar.addWidget(self._undo_auto_btn)
        mw_layout.addLayout(m_bar)
        mw_layout.addWidget(self._matched_table)

        self._tabs.addTab(matched_wrap, "Matched")
        self._tabs.addTab(unmatched_wrap, "Unmatched Statement")
        self._tabs.addTab(self._unmatched_book_table, "Unmatched Book")
        self._tabs.addTab(self._ignored_table, "Ignored")
        layout.addWidget(self._tabs, 1)

        return page

    def _refresh_bulk_buttons(self):
        n = len(self._selected_stmt_line_ids())
        # Hide buttons entirely when no selection — gives back ~120px of
        # horizontal room and signals "select first" by their absence.
        self._bulk_voucher_btn.setVisible(n > 0)
        self._bulk_ignore_btn.setVisible(n > 0)
        if n == 0:
            self._bulk_label.setText("")
        else:
            self._bulk_label.setText(f"<b>{n}</b> selected")

    def _apply_stmt_filter(self, text: str):
        """Hide rows whose narration / reference don't contain the search
        text (case-insensitive substring). Empty filter shows all rows."""
        needle = (text or "").strip().lower()
        t = self._unmatched_stmt_table
        for r in range(t.rowCount()):
            if not needle:
                t.setRowHidden(r, False)
                continue
            narr = (t.item(r, 3).text() if t.item(r, 3) else "").lower()
            ref  = (t.item(r, 4).text() if t.item(r, 4) else "").lower()
            t.setRowHidden(r, needle not in narr and needle not in ref)

    def _select_all_visible_stmt_rows(self):
        """Select every NON-HIDDEN row on the Unmatched Statement table.
        Pairs with the filter input — type 'JIO' → click → bulk-act."""
        t = self._unmatched_stmt_table
        t.clearSelection()
        sel = t.selectionModel()
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        selection = QItemSelection()
        for r in range(t.rowCount()):
            if t.isRowHidden(r):
                continue
            top    = t.model().index(r, 0)
            bottom = t.model().index(r, t.columnCount() - 1)
            selection.select(top, bottom)
        sel.select(
            selection,
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )

    def _selected_stmt_line_ids(self) -> list[int]:
        """Return the bank_statement_lines.id values for the rows the
        user has selected on the Unmatched Statement table. Row → id is
        carried on column-0's QTableWidgetItem via Qt.UserRole."""
        ids: list[int] = []
        for r in sorted({i.row() for i in
                          self._unmatched_stmt_table.selectedItems()}):
            item = self._unmatched_stmt_table.item(r, 0)
            if item is None:
                continue
            lid = item.data(Qt.ItemDataRole.UserRole)
            if lid:
                ids.append(int(lid))
        return ids

    @staticmethod
    def _compact_btn(text: str) -> QPushButton:
        """Small button sized to sit comfortably inside a 52px table row."""
        b = QPushButton(text)
        b.setFixedHeight(28)
        b.setStyleSheet(f"""
            QPushButton {{
                background:{THEME['bg_input']};
                border:1px solid {THEME['border']};
                border-radius:5px;
                padding:0px 10px;
                font-size:11px;
                color:{THEME['text_primary']};
                min-height:0;
            }}
            QPushButton:hover {{
                border-color:{THEME['accent']};
                color:{THEME['accent']};
            }}
        """)
        return b

    @staticmethod
    def _make_table(headers: list[str], widths: list[int]) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        # 32px rows: enough for the 28px _compact_btn action buttons but
        # ~60% denser than the old 52px. On a 750-line statement this is
        # the difference between 5 visible rows and ~14.
        t.verticalHeader().setDefaultSectionSize(32)
        # Override the global QTableWidget::item padding (8 12) which
        # would force the visual row height up regardless of the section
        # size. The bank-reco tables are dense-by-design; the rest of the
        # app keeps the airier global padding.
        t.setStyleSheet(
            "QTableWidget::item { padding: 2px 8px; }"
            "QHeaderView::section { padding: 4px 8px; }"
        )
        hdr = t.horizontalHeader()
        for i, w in enumerate(widths):
            if w == 0:
                hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                t.setColumnWidth(i, w)
        make_sortable(t)
        return t

    def _populate_review(self):
        if self._statement_id is None:
            return

        # Matched
        matched = self.reconciler.matched_lines(self._statement_id)
        with populating(self._matched_table):
            self._matched_table.setRowCount(len(matched))
            for r, m in enumerate(matched):
                self._matched_table.setItem(r, 0, DateTableItem(m["txn_date"]))
                self._matched_table.setItem(r, 1, QTableWidgetItem(m["sign"]))
                self._matched_table.setItem(r, 2, NumericTableItem(
                    f"₹ {m['amount']:,.2f}", m["amount"]
                ))
                self._matched_table.setItem(r, 3, QTableWidgetItem(m.get("voucher_number") or ""))
                self._matched_table.setItem(r, 4, QTableWidgetItem(m.get("voucher_type") or ""))
                self._matched_table.setItem(r, 5, QTableWidgetItem(m.get("narration") or ""))
                unmatch_btn = self._compact_btn("Unmatch")
                unmatch_btn.clicked.connect(
                    lambda _, sl_id=m["id"]: self._on_unmatch(sl_id)
                )
                cell = QWidget()
                ch = QHBoxLayout(cell)
                ch.setContentsMargins(6, 0, 6, 0)
                ch.addWidget(unmatch_btn)
                ch.addStretch()
                self._matched_table.setCellWidget(r, 6, cell)

        # Unmatched stmt
        u_stmt = self.reconciler.unmatched_statement_lines(self._statement_id)
        with populating(self._unmatched_stmt_table):
            self._unmatched_stmt_table.setRowCount(len(u_stmt))
            for r, s in enumerate(u_stmt):
                date_item = DateTableItem(s["txn_date"])
                # Carry the statement_line.id on column 0 so multi-select
                # bulk actions can map row → id.
                date_item.setData(Qt.ItemDataRole.UserRole, s["id"])
                self._unmatched_stmt_table.setItem(r, 0, date_item)
                self._unmatched_stmt_table.setItem(r, 1, QTableWidgetItem(s["sign"]))
                self._unmatched_stmt_table.setItem(r, 2, NumericTableItem(
                    f"₹ {s['amount']:,.2f}", s["amount"]
                ))
                self._unmatched_stmt_table.setItem(r, 3, QTableWidgetItem(s.get("narration") or ""))
                self._unmatched_stmt_table.setItem(r, 4, QTableWidgetItem(s.get("reference") or ""))
                self._unmatched_stmt_table.setItem(r, 5, QTableWidgetItem(s["match_status"]))

                actions = QWidget()
                ah = QHBoxLayout(actions)
                ah.setContentsMargins(6, 0, 6, 0)
                ah.setSpacing(4)
                cv = self._compact_btn("Create voucher")
                cv.clicked.connect(lambda _, line=s: self._on_create_voucher(line))
                fc = self._compact_btn("Find candidate")
                fc.clicked.connect(lambda _, line=s: self._on_find_candidate(line))
                ah.addWidget(cv)
                ah.addWidget(fc)
                # Split-match: settlement scenarios where one bank line pairs
                # with N book lines summing to the bank amount. Standard+ only.
                if self._has_feature("bank_reco_split"):
                    sm = self._compact_btn("Split match")
                    sm.setToolTip(
                        "Match this bank line to several ledger entries that "
                        "together total the bank amount (settlement scenario)."
                    )
                    sm.clicked.connect(lambda _, line=s: self._on_split_match(line))
                    ah.addWidget(sm)
                ig = self._compact_btn("Ignore")
                ig.clicked.connect(lambda _, line=s: self._on_ignore(line))
                ah.addWidget(ig)
                ah.addStretch()
                self._unmatched_stmt_table.setCellWidget(r, 6, actions)

        # Unmatched book
        u_book = self.reconciler.unmatched_book_lines(
            self._bank_ledger_id, self._period_from, self._period_to,
        )
        with populating(self._unmatched_book_table):
            self._unmatched_book_table.setRowCount(len(u_book))
            for r, b in enumerate(u_book):
                self._unmatched_book_table.setItem(r, 0, DateTableItem(b["voucher_date"]))
                self._unmatched_book_table.setItem(r, 1, QTableWidgetItem(b["voucher_number"] or ""))
                self._unmatched_book_table.setItem(r, 2, QTableWidgetItem(b["voucher_type"]))
                amt = (
                    f"Dr ₹ {b['dr_amount']:,.2f}"
                    if b["dr_amount"] else
                    f"Cr ₹ {b['cr_amount']:,.2f}"
                )
                amt_val = float(b["dr_amount"] or b["cr_amount"] or 0)
                self._unmatched_book_table.setItem(r, 3, NumericTableItem(amt, amt_val))
                self._unmatched_book_table.setItem(r, 4, QTableWidgetItem(b.get("narration") or ""))

                mark = self._compact_btn("Mark cleared")
                mark.clicked.connect(
                    lambda _, vl_id=b["id"]: self._on_mark_book_cleared(vl_id)
                )
                cell = QWidget()
                ch = QHBoxLayout(cell)
                ch.setContentsMargins(6, 0, 6, 0)
                ch.addWidget(mark)
                ch.addStretch()
                self._unmatched_book_table.setCellWidget(r, 5, cell)

        # Ignored — separate tab so resolved-as-ignored lines don't crowd
        # the Unmatched view but stay reviewable.
        ignored = self.reconciler.ignored_statement_lines(self._statement_id)
        with populating(self._ignored_table):
            self._ignored_table.setRowCount(len(ignored))
            for r, s in enumerate(ignored):
                self._ignored_table.setItem(r, 0, DateTableItem(s["txn_date"]))
                self._ignored_table.setItem(r, 1, QTableWidgetItem(s["sign"]))
                self._ignored_table.setItem(r, 2, NumericTableItem(
                    f"₹ {s['amount']:,.2f}", s["amount"]
                ))
                self._ignored_table.setItem(r, 3, QTableWidgetItem(s.get("narration") or ""))
                self._ignored_table.setItem(r, 4, QTableWidgetItem(s.get("reference") or ""))
                self._ignored_table.setItem(r, 5, QTableWidgetItem(s.get("notes") or ""))
                unignore = self._compact_btn("Un-ignore")
                unignore.clicked.connect(
                    lambda _, sl_id=s["id"]: self._on_unignore(sl_id)
                )
                cell = QWidget()
                ch = QHBoxLayout(cell)
                ch.setContentsMargins(6, 0, 6, 0)
                ch.addWidget(unignore)
                ch.addStretch()
                self._ignored_table.setCellWidget(r, 6, cell)

        # Update tab labels with counts so the user sees at-a-glance what
        # needs attention vs what's already resolved.
        self._tabs.setTabText(0, f"Matched ({len(matched)})")
        self._tabs.setTabText(1, f"Unmatched Statement ({len(u_stmt)})")
        self._tabs.setTabText(2, f"Unmatched Book ({len(u_book)})")
        self._tabs.setTabText(3, f"Ignored ({len(ignored)})")

        self._refresh_bulk_buttons()
        # Re-apply the user's filter after repopulating — important when
        # they batch-act on JIO lines and the remaining unmatched should
        # still be filtered to JIO so they can verify.
        try:
            self._apply_stmt_filter(self._stmt_filter.text())
        except Exception:
            pass
        self._review_summary.setText(
            f"  ✓ {len(matched)} matched   |   "
            f"⚠ {len(u_stmt)} stmt unmatched   |   "
            f"⚠ {len(u_book)} book unmatched   |   "
            f"⊘ {len(ignored)} ignored"
        )

        # Update the bento KPI strip with the same numbers + colour
        # the status by load (more unmatched = more amber/red).
        try:
            if self._kpi_matched is not None:
                self._kpi_matched.set_value(str(len(matched)))
                self._kpi_matched.set_delta(
                    f"{round(100*len(matched)/max(1, len(matched)+len(u_stmt)+len(u_book)))}% of all lines"
                )
            if self._kpi_unmatched is not None:
                self._kpi_unmatched.set_value(str(len(u_stmt)))
                self._kpi_unmatched.set_delta("need a voucher or match")
            if self._kpi_book is not None:
                self._kpi_book.set_value(str(len(u_book)))
                self._kpi_book.set_delta("vouchers w/o a bank line")
            if self._kpi_ignored is not None:
                self._kpi_ignored.set_value(str(len(ignored)))
                self._kpi_ignored.set_delta("intentionally skipped")
        except Exception:
            pass

    def _on_unignore(self, statement_line_id: int):
        """Move an ignored line back to UNMATCHED so the user can act on it."""
        try:
            self.reconciler.unmatch(statement_line_id)
        except Exception as e:
            QMessageBox.critical(self, "Un-ignore failed", str(e))
            return
        self._populate_review()

    # ── Bulk actions ──────────────────────────────────────────────────────────

    def _on_bulk_ignore(self):
        ids = self._selected_stmt_line_ids()
        if not ids:
            return
        note, ok = QInputDialog.getText(
            self, f"Ignore {len(ids)} line(s)",
            "Optional note applied to all selected lines "
            "(e.g. 'reversed', 'duplicate', 'personal expense'):",
        )
        if not ok:
            return
        try:
            n = self.reconciler.bulk_ignore(ids, note=note)
        except Exception as e:
            QMessageBox.critical(self, "Bulk ignore failed", str(e))
            return
        QMessageBox.information(
            self, "Done", f"{n} line(s) moved to the Ignored tab."
        )
        self._populate_review()

    def _on_bulk_create_voucher(self):
        ids = self._selected_stmt_line_ids()
        if not ids:
            return
        dlg = _BulkCreateVoucherDialog(
            self.reconciler, self.tree,
            self._bank_ledger_id, self._bank_ledger_name,
            stmt_line_ids=ids,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._populate_review()

    def _on_unmatch(self, statement_line_id: int):
        try:
            self.reconciler.unmatch(statement_line_id)
        except Exception as e:
            QMessageBox.critical(self, "Unmatch failed", str(e))
            return
        self._populate_review()

    def _on_undo_auto_matches(self):
        if self._statement_id is None:
            return
        confirm = QMessageBox.question(
            self,
            "Undo auto-matches?",
            "This will revert every auto-matched row on this statement "
            "back to Unmatched. Manual matches and created vouchers are "
            "left alone. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            n = self.reconciler.unmatch_all_auto(self._statement_id)
        except Exception as e:
            QMessageBox.critical(self, "Undo failed", str(e))
            return
        self._populate_review()
        QMessageBox.information(
            self, "Undo complete",
            f"Reverted {n} auto-matched row(s) back to Unmatched."
        )

    def _on_create_voucher(self, stmt_line: dict):
        dlg = _CreateVoucherDialog(
            self.reconciler, self.tree,
            self._bank_ledger_id, self._bank_ledger_name,
            stmt_line, parent=self,
        )
        dlg.posted.connect(lambda *_: self._populate_review())
        dlg.exec()

    def _has_feature(self, feature: str) -> bool:
        try:
            return bool(self.license_mgr.has_feature(feature))
        except Exception:
            return False

    def _on_find_candidate(self, stmt_line: dict):
        candidates = self.reconciler.candidate_book_lines(
            self._bank_ledger_id, stmt_line["txn_date"],
            float(stmt_line["amount"]), stmt_line["sign"],
        )
        dlg = _FindCandidateDialog(
            candidates,
            stmt_sign=stmt_line["sign"],
            stmt_amount=float(stmt_line["amount"]),
            split_mode=False,
            parent=self,
        )

        def _on_pick(vl_id: int):
            try:
                self.reconciler.manual_match(stmt_line["id"], vl_id)
            except Exception as e:
                QMessageBox.critical(self, "Match failed", str(e))
                return
            self._populate_review()

        dlg.picked.connect(_on_pick)
        dlg.exec()

    def _on_split_match(self, stmt_line: dict):
        """Settlement match — one bank line ↔ many book entries summing to
        the bank amount. Standard+ only (bank_reco_split feature)."""
        if not self._has_feature("bank_reco_split"):
            return
        candidates = self.reconciler.candidate_book_lines(
            self._bank_ledger_id, stmt_line["txn_date"],
            float(stmt_line["amount"]), stmt_line["sign"],
            split_mode=True,
        )
        dlg = _FindCandidateDialog(
            candidates,
            stmt_sign=stmt_line["sign"],
            stmt_amount=float(stmt_line["amount"]),
            split_mode=True,
            parent=self,
        )

        def _on_pick_many(vl_ids: list):
            try:
                self.reconciler.manual_match_many(stmt_line["id"], vl_ids)
            except Exception as e:
                QMessageBox.critical(self, "Match failed", str(e))
                return
            self._populate_review()

        dlg.picked_many.connect(_on_pick_many)
        dlg.exec()

    def _on_ignore(self, stmt_line: dict):
        # Pref governs whether we even prompt for a note. Off = silent ignore.
        from core.user_prefs import prefs as _prefs
        note = ""
        if _prefs.get("bank_reco_comment_on_ignore", True):
            note, ok = QInputDialog.getText(
                self, "Ignore line",
                "Optional note (e.g. 'duplicate', 'bank fee already booked'):",
            )
            if not ok:
                return
        try:
            self.reconciler.mark_ignored(stmt_line["id"], note=note)
        except Exception as e:
            QMessageBox.critical(self, "Ignore failed", str(e))
            return
        self._populate_review()

    def _on_mark_book_cleared(self, voucher_line_id: int):
        as_of = self._period_to_edit.date().toString("yyyy-MM-dd")
        try:
            self.reconciler.mark_book_line_cleared(voucher_line_id, as_of)
        except Exception as e:
            QMessageBox.critical(self, "Mark cleared failed", str(e))
            return
        self._populate_review()

    # ── Step 3: Summary ───────────────────────────────────────────────────────

    def _build_summary_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        bar = QHBoxLayout()
        back_btn = QPushButton("← Back to Review")
        back_btn.clicked.connect(
            lambda: self._stack.setCurrentWidget(self._review_page)
        )
        bar.addWidget(back_btn)
        bar.addStretch()
        layout.addLayout(bar)

        card = QFrame()
        card.setObjectName("card")
        clay = QVBoxLayout(card)
        clay.setContentsMargins(28, 24, 28, 24)
        clay.setSpacing(14)

        self._summary_book = QLabel("Book balance: ₹ 0.00")
        self._summary_book.setStyleSheet(
            f"color:{THEME['text_primary']}; font-size:14px;"
        )
        clay.addWidget(self._summary_book)

        self._summary_stmt = QLabel("Statement balance: —")
        self._summary_stmt.setStyleSheet(
            f"color:{THEME['text_primary']}; font-size:14px;"
        )
        clay.addWidget(self._summary_stmt)

        self._summary_diff = QLabel("Difference: ₹ 0.00")
        self._summary_diff.setStyleSheet(
            f"color:{THEME['accent']}; font-size:16px; font-weight:bold;"
        )
        clay.addWidget(self._summary_diff)

        self._summary_counts = QLabel("")
        self._summary_counts.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        clay.addWidget(self._summary_counts)

        self._summary_notes = QPlainTextEdit()
        self._summary_notes.setPlaceholderText("Notes (optional)")
        self._summary_notes.setFixedHeight(80)
        clay.addWidget(self._summary_notes)

        layout.addWidget(card)

        finalise_row = QHBoxLayout()
        finalise_row.addStretch()
        finalise_btn = QPushButton("Finalise reconciliation")
        finalise_btn.setObjectName("btn_primary")
        finalise_btn.setFixedHeight(40)
        finalise_btn.clicked.connect(self._on_finalise)
        finalise_row.addWidget(finalise_btn)
        layout.addLayout(finalise_row)

        layout.addStretch()
        return page

    def _go_to_summary(self):
        if self._statement_id is None:
            return
        # Compute current numbers for the summary card
        stmt = self.db.execute(
            "SELECT period_to, statement_closing FROM bank_statements WHERE id=?",
            (self._statement_id,),
        ).fetchone()
        as_of = stmt["period_to"]
        book = self.reconciler._book_balance(self._bank_ledger_id, as_of)
        stmt_close = stmt["statement_closing"]
        self._summary_book.setText(f"Book balance: ₹ {book:,.2f}")
        if stmt_close is None:
            self._summary_stmt.setText("Statement balance: not detected from import")
            diff = 0.0
        else:
            self._summary_stmt.setText(f"Statement balance: ₹ {stmt_close:,.2f}")
            diff = round(book - stmt_close, 2)
        if abs(diff) < 0.01:
            self._summary_diff.setText("Difference: ✓ ₹ 0.00 (reconciled)")
            self._summary_diff.setStyleSheet(
                f"color:{THEME['success']}; font-size:16px; font-weight:bold;"
            )
        else:
            self._summary_diff.setText(f"Difference: ₹ {diff:,.2f}")
            self._summary_diff.setStyleSheet(
                f"color:{THEME['danger']}; font-size:16px; font-weight:bold;"
            )

        u_stmt = len(self.reconciler.unmatched_statement_lines(self._statement_id))
        u_book = len(self.reconciler.unmatched_book_lines(
            self._bank_ledger_id, self._period_from, self._period_to,
        ))
        self._summary_counts.setText(
            f"Unmatched: {u_stmt} statement line(s) · {u_book} ledger entr(ies)"
        )

        self._stack.setCurrentWidget(self._summary_page)

    def _on_finalise(self):
        if self._statement_id is None:
            return
        try:
            recon_id = self.reconciler.finalise(
                self._statement_id,
                notes=self._summary_notes.toPlainText().strip(),
            )
        except Exception as e:
            QMessageBox.critical(self, "Finalise failed", str(e))
            return

        QMessageBox.information(
            self, "Finalised",
            f"Reconciliation snapshot saved (id {recon_id}).",
        )
        # Reset session and return to setup
        self._statement_id = None
        self._refresh_history()
        self._stack.setCurrentWidget(self._setup_page)
