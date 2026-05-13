"""
Ledger Reconciliation page UI.

Three steps mirroring Bank Reconciliation:
    Step 1 — Setup:    pick a non-bank-non-cash ledger, period, sign mode,
                       drop a statement file
    Step 2 — Review:   3 tabs (Matched / Unmatched stmt / Unmatched book)
    Step 3 — Summary:  balances + Finalise
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QDateEdit, QLineEdit,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QTabWidget, QDialog,
    QFormLayout, QInputDialog, QPlainTextEdit, QButtonGroup,
    QRadioButton,
)
from PySide6.QtCore import Qt, QDate, Signal, QThread

from ui.theme import THEME
from ui.widgets import FilteredLedgerSearchEdit, SmartDateEdit
from core.ledger_reconciliation import (
    LedgerReconciler, LocalParseFailed,
)
from core.voucher_engine import VoucherDraft, VoucherLine


# ── Background worker ───────────────────────────────────────────────────────

class _ImportThread(QThread):
    progress     = Signal(str)
    finished     = Signal(int, object)
    local_failed = Signal(str)
    error        = Signal(str)

    def __init__(self, reconciler, ledger_id, file_path,
                 sign_mode, period_from, period_to):
        super().__init__()
        self.reconciler = reconciler
        self.ledger_id  = ledger_id
        self.file_path  = file_path
        self.sign_mode  = sign_mode
        self.period_from = period_from
        self.period_to   = period_to

    def run(self):
        try:
            self.progress.emit("Parsing locally…")
            stmt_id = self.reconciler.import_statement(
                ledger_id=self.ledger_id,
                file_path=self.file_path,
                sign_mode=self.sign_mode,
                period_from=self.period_from,
                period_to=self.period_to,
            )
            self.progress.emit("Matching against ledger entries…")
            result = self.reconciler.auto_match(stmt_id)
            self.finished.emit(stmt_id, result)
        except LocalParseFailed as e:
            self.local_failed.emit(str(e))
        except Exception as e:
            self.error.emit(str(e))


# ── Main page ───────────────────────────────────────────────────────────────

class LedgerReconciliationPage(QWidget):

    def __init__(self, db, company_id, tree, voucher_engine, calculator,
                 license_mgr, parent=None):
        super().__init__(parent)
        self.db          = db
        self.company_id  = company_id
        self.tree        = tree
        self.engine      = voucher_engine
        self.calculator  = calculator
        self.license_mgr = license_mgr
        self.reconciler  = LedgerReconciler(db, company_id, tree)

        self._statement_id: int | None = None
        self._ledger_id: int | None = None
        self._ledger_name: str = ""
        self._period_from: str = ""
        self._period_to: str = ""
        self._sign_mode: str = "MIRROR"
        self._pending_file_path: str = ""
        self._import_thread: _ImportThread | None = None

        self._build_ui()

    @staticmethod
    def _compact_btn(text: str) -> QPushButton:
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
    def _make_table(headers, widths):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(52)
        hdr = t.horizontalHeader()
        for i, w in enumerate(widths):
            if w == 0:
                hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                t.setColumnWidth(i, w)
        return t

    # ── UI scaffolding ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 0, 24, 24)
        root.setSpacing(0)

        title = QLabel("Ledger Reconciliation")
        title.setObjectName("page_title")
        root.addWidget(title)
        sub = QLabel("Match a party / non-bank ledger against an external statement.")
        sub.setObjectName("page_subtitle")
        root.addWidget(sub)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        self._setup_page   = self._build_setup_page()
        self._review_page  = self._build_review_page()
        self._summary_page = self._build_summary_page()
        self._stack.addWidget(self._setup_page)
        self._stack.addWidget(self._review_page)
        self._stack.addWidget(self._summary_page)

    # ── Step 1 — Setup ──────────────────────────────────────────────────────

    def _build_setup_page(self) -> QWidget:
        from ui.document_reader_page import DropZone, _load_cfg, _save_cfg
        self._load_cfg = _load_cfg
        self._save_cfg = _save_cfg

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # ── Picker + period + sign mode ──
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 14)
        cl.setSpacing(12)

        pick_row = QHBoxLayout()
        plbl = QLabel("Ledger")
        plbl.setFixedWidth(120)
        plbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        pick_row.addWidget(plbl)
        # Filter to non-bank, non-cash ledgers
        all_ledgers = self.tree.get_all_ledgers()
        eligible = [
            l for l in all_ledgers
            if not l.get("is_bank") and not l.get("is_cash")
            and not l.get("is_gst_ledger")
        ]
        self._ledger_picker = FilteredLedgerSearchEdit(
            self.tree, calculator=None,
            ledger_list=eligible,
            placeholder="Pick a ledger to reconcile…",
        )
        self._ledger_picker.ledger_selected.connect(self._on_ledger_picked)
        pick_row.addWidget(self._ledger_picker, 1)
        cl.addLayout(pick_row)

        period_row = QHBoxLayout()
        plbl2 = QLabel("Period")
        plbl2.setFixedWidth(120)
        plbl2.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        period_row.addWidget(plbl2)
        today = QDate.currentDate()
        fy_start = QDate(
            today.year() if today.month() >= 4 else today.year() - 1, 4, 1
        )
        self._period_from_edit = SmartDateEdit(fy_start)
        self._period_from_edit.setDisplayFormat("dd-MMM-yyyy")
        self._period_from_edit.setFixedHeight(34)
        period_row.addWidget(self._period_from_edit)
        period_row.addWidget(QLabel("→"))
        self._period_to_edit = SmartDateEdit(today)
        self._period_to_edit.setDisplayFormat("dd-MMM-yyyy")
        self._period_to_edit.setFixedHeight(34)
        period_row.addWidget(self._period_to_edit)
        period_row.addStretch()
        cl.addLayout(period_row)

        # Sign mode radios
        sign_row = QHBoxLayout()
        slbl = QLabel("File POV")
        slbl.setFixedWidth(120)
        slbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        sign_row.addWidget(slbl)

        self._sign_group = QButtonGroup(self)
        self._mirror_radio = QRadioButton(
            "Their statement (Mirror — their Dr ↔ our Cr)"
        )
        self._mirror_radio.setChecked(True)
        self._sign_group.addButton(self._mirror_radio)
        sign_row.addWidget(self._mirror_radio)

        self._same_radio = QRadioButton(
            "Our ledger from another system (no flip)"
        )
        self._sign_group.addButton(self._same_radio)
        sign_row.addWidget(self._same_radio)
        sign_row.addStretch()
        cl.addLayout(sign_row)

        layout.addWidget(card)

        # ── Drop zone ──
        drop_card = QFrame()
        drop_card.setObjectName("card")
        dl = QVBoxLayout(drop_card)
        dl.setContentsMargins(20, 14, 20, 14)
        dl.setSpacing(8)
        dt = QLabel("Statement file")
        dt.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        dl.addWidget(dt)
        hint = QLabel(
            "CSV, Excel and text-PDF parse locally for free. Scanned PDFs "
            "and unusual layouts aren't yet supported here — export from "
            "your party's books as CSV / Excel."
        )
        hint.setStyleSheet(f"color:{THEME['text_dim']}; font-size:10px;")
        hint.setWordWrap(True)
        dl.addWidget(hint)

        self._drop = DropZone()
        self._drop.file_dropped.connect(self._on_file_dropped)
        dl.addWidget(self._drop)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        self._status_lbl.setWordWrap(True)
        dl.addWidget(self._status_lbl)
        layout.addWidget(drop_card)

        # ── Imported statements + history ──
        imp_card = QFrame()
        imp_card.setObjectName("card")
        il = QVBoxLayout(imp_card)
        il.setContentsMargins(20, 14, 20, 14)
        il.setSpacing(8)
        it_title = QLabel("Imported statements for this ledger")
        it_title.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        il.addWidget(it_title)
        self._imports_table = QTableWidget(0, 6)
        self._imports_table.setHorizontalHeaderLabels(
            ["File", "Period", "Sign", "Lines (m / u / o)", "Status", ""]
        )
        self._imports_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        h = self._imports_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, w in ((1, 180), (2, 80), (3, 130), (4, 100), (5, 100)):
            h.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self._imports_table.setColumnWidth(col, w)
        self._imports_table.verticalHeader().setDefaultSectionSize(40)
        self._imports_table.setMinimumHeight(120)
        il.addWidget(self._imports_table)

        ht_title = QLabel("Past reconciliations")
        ht_title.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; "
            f"font-weight:bold; padding-top:10px;"
        )
        il.addWidget(ht_title)
        self._history_table = QTableWidget(0, 4)
        self._history_table.setHorizontalHeaderLabels(
            ["As of", "Book bal.", "Stmt bal.", "Finalised"]
        )
        self._history_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._history_table.verticalHeader().setDefaultSectionSize(36)
        self._history_table.setMinimumHeight(100)
        il.addWidget(self._history_table)
        layout.addWidget(imp_card)

        return page

    def _on_ledger_picked(self, ledger_id, name, _row):
        self._ledger_id   = ledger_id
        self._ledger_name = name
        self._refresh_history()
        self._auto_fill_period()

    def _auto_fill_period(self):
        if not self._ledger_id:
            return
        last = self.reconciler.last_party_cleared_date(self._ledger_id)
        today = QDate.currentDate()
        if last:
            try:
                start = date.fromisoformat(last) + timedelta(days=1)
                qs = QDate(start.year, start.month, start.day)
            except ValueError:
                qs = self._period_from_edit.date()
        else:
            y = today.year() if today.month() >= 4 else today.year() - 1
            qs = QDate(y, 4, 1)
        self._period_from_edit.setDate(qs)
        self._period_to_edit.setDate(today)

    def _refresh_history(self):
        self._imports_table.setRowCount(0)
        self._history_table.setRowCount(0)
        if not self._ledger_id:
            return
        for r, row in enumerate(self.reconciler.recent_imports(self._ledger_id)):
            self._imports_table.insertRow(r)
            self._imports_table.setItem(r, 0, QTableWidgetItem(row["file_name"]))
            self._imports_table.setItem(r, 1, QTableWidgetItem(
                f"{row['period_from']}  →  {row['period_to']}"
            ))
            self._imports_table.setItem(r, 2, QTableWidgetItem(row["sign_mode"]))
            self._imports_table.setItem(r, 3, QTableWidgetItem(
                f"{row['matched']} / {row['unmatched']} / {row['resolved_other']}"
            ))
            self._imports_table.setItem(r, 4, QTableWidgetItem(
                "Finalised" if row["finalised"] else "In progress"
            ))
            del_btn = self._compact_btn("Delete")
            del_btn.clicked.connect(
                lambda _, sid=row["id"], summary=row:
                self._on_delete_statement(sid, summary)
            )
            cell = QWidget()
            ch = QHBoxLayout(cell)
            ch.setContentsMargins(6, 0, 6, 0)
            ch.addWidget(del_btn)
            ch.addStretch()
            self._imports_table.setCellWidget(r, 5, cell)

        for r, row in enumerate(self.reconciler.history_for_ledger(self._ledger_id)):
            self._history_table.insertRow(r)
            self._history_table.setItem(r, 0, QTableWidgetItem(row["as_of_date"]))
            self._history_table.setItem(r, 1, QTableWidgetItem(
                f"₹ {row['book_balance']:,.2f}"
            ))
            self._history_table.setItem(r, 2, QTableWidgetItem(
                f"₹ {row['statement_balance']:,.2f}"
            ))
            self._history_table.setItem(r, 3, QTableWidgetItem(
                row["finalised_at"][:16]
            ))

    def _on_delete_statement(self, statement_id: int, summary: dict):
        matched = summary.get("matched") or 0
        warn = ""
        if matched:
            warn = (
                f"\n\nThis statement has {matched} matched line(s). "
                "Deleting it will reset party_cleared_date on those lines."
            )
        reply = QMessageBox.question(
            self, "Delete statement?",
            f"Delete '{summary.get('file_name')}' "
            f"({summary.get('period_from')} → {summary.get('period_to')})?{warn}",
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
        if not self._ledger_id:
            QMessageBox.warning(
                self, "Pick a ledger first",
                "Select a ledger before importing a statement.",
            )
            return
        self._pending_file_path = path
        self._period_from = self._period_from_edit.date().toString("yyyy-MM-dd")
        self._period_to   = self._period_to_edit.date().toString("yyyy-MM-dd")
        self._sign_mode   = "MIRROR" if self._mirror_radio.isChecked() else "SAME"
        self._fire_import()

    def _fire_import(self):
        self._status_lbl.setText("Parsing locally…")
        self._import_thread = _ImportThread(
            self.reconciler, self._ledger_id, self._pending_file_path,
            self._sign_mode, self._period_from, self._period_to,
        )
        self._import_thread.progress.connect(self._status_lbl.setText)
        self._import_thread.finished.connect(self._on_import_done)
        self._import_thread.local_failed.connect(self._on_local_failed)
        self._import_thread.error.connect(self._on_import_error)
        self._import_thread.start()

    def _on_local_failed(self, err: str):
        self._status_lbl.setText("")
        QMessageBox.warning(
            self, "Local parse failed",
            f"{err}\n\nLedger reconciliation only supports the local "
            "parser today. Export your party's data as CSV / Excel.",
        )

    def _on_import_error(self, msg: str):
        self._status_lbl.setText("")
        QMessageBox.critical(self, "Import failed", msg)

    def _on_import_done(self, statement_id: int, result):
        self._statement_id = statement_id
        self._status_lbl.setText(
            f"Imported. Matched {result.matched}, "
            f"{result.unmatched_stmt} stmt unmatched, "
            f"{result.unmatched_book} book unmatched."
        )
        self._populate_review()
        self._stack.setCurrentWidget(self._review_page)

    # ── Step 2 — Review ────────────────────────────────────────────────────

    def _build_review_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        bar = QHBoxLayout()
        back_btn = QPushButton("← Back to Setup")
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
        self._unmatched_book_table = self._make_table(
            ["Date", "Voucher #", "Type", "Amount", "Narration", ""],
            [110, 130, 90, 130, 0, 140],
        )
        self._ignored_table = self._make_table(
            ["Date", "Sign", "Amount", "Narration", "Reference", "Note", ""],
            [110, 60, 120, 0, 130, 200, 110],
        )
        self._tabs.addTab(self._matched_table,         "Matched")
        self._tabs.addTab(self._unmatched_stmt_table,  "Unmatched Statement")
        self._tabs.addTab(self._unmatched_book_table,  "Unmatched Book")
        self._tabs.addTab(self._ignored_table,         "Ignored")
        layout.addWidget(self._tabs, 1)
        return page

    def _populate_review(self):
        if self._statement_id is None:
            return

        matched = self.reconciler.matched_lines(self._statement_id)
        self._matched_table.setRowCount(len(matched))
        for r, m in enumerate(matched):
            self._matched_table.setItem(r, 0, QTableWidgetItem(m["txn_date"]))
            self._matched_table.setItem(r, 1, QTableWidgetItem(m["sign"]))
            self._matched_table.setItem(r, 2, QTableWidgetItem(f"₹ {m['amount']:,.2f}"))
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

        u_stmt = self.reconciler.unmatched_statement_lines(self._statement_id)
        self._unmatched_stmt_table.setRowCount(len(u_stmt))
        for r, s in enumerate(u_stmt):
            self._unmatched_stmt_table.setItem(r, 0, QTableWidgetItem(s["txn_date"]))
            self._unmatched_stmt_table.setItem(r, 1, QTableWidgetItem(s["sign"]))
            self._unmatched_stmt_table.setItem(r, 2, QTableWidgetItem(
                f"₹ {s['amount']:,.2f}"
            ))
            self._unmatched_stmt_table.setItem(r, 3, QTableWidgetItem(s.get("narration") or ""))
            self._unmatched_stmt_table.setItem(r, 4, QTableWidgetItem(s.get("reference") or ""))
            self._unmatched_stmt_table.setItem(r, 5, QTableWidgetItem(s["match_status"]))
            actions = QWidget()
            ah = QHBoxLayout(actions)
            ah.setContentsMargins(6, 0, 6, 0)
            ah.setSpacing(4)
            cv = self._compact_btn("Add voucher")
            cv.clicked.connect(lambda _, line=s: self._on_create_voucher(line))
            fc = self._compact_btn("Find candidate")
            fc.clicked.connect(lambda _, line=s: self._on_find_candidate(line))
            ig = self._compact_btn("Ignore")
            ig.clicked.connect(lambda _, line=s: self._on_ignore(line))
            ah.addWidget(cv)
            ah.addWidget(fc)
            ah.addWidget(ig)
            ah.addStretch()
            self._unmatched_stmt_table.setCellWidget(r, 6, actions)

        u_book = self.reconciler.unmatched_book_lines(
            self._ledger_id, self._period_from, self._period_to,
        )
        self._unmatched_book_table.setRowCount(len(u_book))
        for r, b in enumerate(u_book):
            self._unmatched_book_table.setItem(r, 0, QTableWidgetItem(b["voucher_date"]))
            self._unmatched_book_table.setItem(r, 1, QTableWidgetItem(b["voucher_number"] or ""))
            self._unmatched_book_table.setItem(r, 2, QTableWidgetItem(b["voucher_type"]))
            amt = (
                f"Dr ₹ {b['dr_amount']:,.2f}" if b["dr_amount"]
                else f"Cr ₹ {b['cr_amount']:,.2f}"
            )
            self._unmatched_book_table.setItem(r, 3, QTableWidgetItem(amt))
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

        ignored = self.reconciler.ignored_statement_lines(self._statement_id)
        self._ignored_table.setRowCount(len(ignored))
        for r, line in enumerate(ignored):
            self._ignored_table.setItem(r, 0, QTableWidgetItem(line["txn_date"]))
            self._ignored_table.setItem(r, 1, QTableWidgetItem(line["sign"]))
            self._ignored_table.setItem(r, 2, QTableWidgetItem(
                f"₹ {line['amount']:,.2f}"
            ))
            self._ignored_table.setItem(r, 3, QTableWidgetItem(line.get("narration") or ""))
            self._ignored_table.setItem(r, 4, QTableWidgetItem(line.get("reference") or ""))
            self._ignored_table.setItem(r, 5, QTableWidgetItem(line.get("notes") or ""))
            restore_btn = self._compact_btn("Restore")
            restore_btn.clicked.connect(
                lambda _, sl_id=line["id"]: self._on_restore_ignored(sl_id)
            )
            cell = QWidget()
            ch = QHBoxLayout(cell)
            ch.setContentsMargins(6, 0, 6, 0)
            ch.addWidget(restore_btn)
            ch.addStretch()
            self._ignored_table.setCellWidget(r, 6, cell)

        self._review_summary.setText(
            f"  ✓ {len(matched)} matched   |   "
            f"⚠ {len(u_stmt)} stmt unmatched   |   "
            f"⚠ {len(u_book)} book unmatched   |   "
            f"⊘ {len(ignored)} ignored"
        )

    def _on_restore_ignored(self, sl_id: int):
        try:
            self.reconciler.restore_ignored(sl_id)
        except Exception as e:
            QMessageBox.critical(self, "Restore failed", str(e))
            return
        self._populate_review()

    def refresh(self):
        """
        Called by MainWindow._select_page after navigation back from
        Add Voucher / Edit Voucher in the main form. Re-fetches the
        review tabs so newly-linked stmt lines appear in Matched.
        """
        self._refresh_history()
        if self._statement_id is not None:
            self._populate_review()

    def _on_create_voucher(self, stmt_line: dict):
        """
        Navigate to the main Post Voucher form prefilled with the party
        ledger pre-placed on the side auto-match would have looked at
        (per sign_mode). The user picks the voucher type — JOURNAL is
        the default, but PAYMENT / RECEIPT / SALES / PURCHASE / DR-CR
        notes all work; on each type switch the prefill re-applies.
        """
        # Side mirrors LedgerReconciler.auto_match's bucket logic
        if self._sign_mode == "MIRROR":
            party_is_dr = (stmt_line["sign"] == "CR")
        else:
            party_is_dr = (stmt_line["sign"] == "DR")
        amount = float(stmt_line["amount"])

        prefill = {
            "voucher_type":      "JOURNAL",
            "voucher_date":      stmt_line["txn_date"],
            "narration":         stmt_line.get("narration") or "",
            "reference":         stmt_line.get("reference") or "",
            "party_ledger_name": self._ledger_name,
            "party_amount":      amount,
            "party_side":        "DR" if party_is_dr else "CR",
        }
        sl_id     = stmt_line["id"]
        ledger_id = self._ledger_id

        def on_posted(posted):
            try:
                self.reconciler.link_voucher_to_stmt_line(
                    statement_line_id=sl_id,
                    voucher_id=posted.voucher_id,
                    ledger_id=ledger_id,
                )
            except Exception as e:
                QMessageBox.warning(self, "Link failed", str(e))

        win = self.window()
        if hasattr(win, "open_voucher_for_create"):
            win.open_voucher_for_create(
                prefill,
                on_post_callback=on_posted,
                banner_text=(
                    f"+ New voucher for {self._ledger_name} · "
                    f"₹ {amount:,.2f} ({prefill['party_side']})  ·  "
                    f"pick a voucher type below"
                ),
            )

    def _on_unmatch(self, sl_id: int):
        try:
            self.reconciler.unmatch(sl_id)
        except Exception as e:
            QMessageBox.critical(self, "Unmatch failed", str(e))
            return
        self._populate_review()

    def _on_find_candidate(self, stmt_line: dict):
        candidates = self.reconciler.candidate_book_lines(
            self._ledger_id, stmt_line["txn_date"],
            float(stmt_line["amount"]), stmt_line["sign"],
            sign_mode=self._sign_mode,
        )
        if not candidates:
            QMessageBox.information(
                self, "No candidates",
                "No uncleared book entries within ±7 days / ±₹1.00 of this line.",
            )
            return
        # Simple picker dialog — just a list with select buttons
        dlg = QDialog(self)
        dlg.setWindowTitle("Find a matching book entry")
        dlg.setMinimumWidth(620)
        dlg.setMinimumHeight(360)
        dl = QVBoxLayout(dlg)
        dl.addWidget(QLabel(f"{len(candidates)} candidate(s):"))
        t = QTableWidget(len(candidates), 5)
        t.setHorizontalHeaderLabels(
            ["Date", "Voucher #", "Type", "Narration", "Amount"]
        )
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        row_to_id: dict[int, int] = {}
        for r, c in enumerate(candidates):
            row_to_id[r] = c["id"]
            t.setItem(r, 0, QTableWidgetItem(c["voucher_date"]))
            t.setItem(r, 1, QTableWidgetItem(c["voucher_number"] or ""))
            t.setItem(r, 2, QTableWidgetItem(c["voucher_type"]))
            t.setItem(r, 3, QTableWidgetItem(c.get("narration") or ""))
            amt = (
                f"Dr ₹ {c['dr_amount']:,.2f}" if c["dr_amount"]
                else f"Cr ₹ {c['cr_amount']:,.2f}"
            )
            t.setItem(r, 4, QTableWidgetItem(amt))
        dl.addWidget(t)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        ok = QPushButton("Match Selected")
        ok.setObjectName("btn_primary")

        def _ok():
            rows = t.selectionModel().selectedRows()
            if not rows:
                QMessageBox.warning(dlg, "Pick one", "Select a candidate row first.")
                return
            vl_id = row_to_id[rows[0].row()]
            try:
                self.reconciler.manual_match(stmt_line["id"], vl_id)
            except Exception as e:
                QMessageBox.critical(dlg, "Match failed", str(e))
                return
            dlg.accept()
            self._populate_review()

        ok.clicked.connect(_ok)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        dl.addLayout(btn_row)
        dlg.exec()

    def _on_ignore(self, stmt_line: dict):
        note, ok = QInputDialog.getText(
            self, "Ignore line",
            "Optional note (e.g. 'duplicate', 'their bank charge'):",
        )
        if not ok:
            return
        try:
            self.reconciler.mark_ignored(stmt_line["id"], note=note)
        except Exception as e:
            QMessageBox.critical(self, "Ignore failed", str(e))
            return
        self._populate_review()

    def _on_mark_book_cleared(self, vl_id: int):
        as_of = self._period_to_edit.date().toString("yyyy-MM-dd")
        try:
            self.reconciler.mark_book_line_cleared(vl_id, as_of)
        except Exception as e:
            QMessageBox.critical(self, "Mark cleared failed", str(e))
            return
        self._populate_review()

    # ── Step 3 — Summary ────────────────────────────────────────────────────

    def _build_summary_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        bar = QHBoxLayout()
        back = QPushButton("← Back to Review")
        back.clicked.connect(
            lambda: self._stack.setCurrentWidget(self._review_page)
        )
        bar.addWidget(back)
        bar.addStretch()
        layout.addLayout(bar)

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(28, 24, 28, 24)
        cl.setSpacing(14)
        self._summary_book = QLabel("Book balance: ₹ 0.00")
        self._summary_book.setStyleSheet(
            f"color:{THEME['text_primary']}; font-size:14px;"
        )
        cl.addWidget(self._summary_book)
        self._summary_stmt = QLabel("Statement balance: —")
        self._summary_stmt.setStyleSheet(
            f"color:{THEME['text_primary']}; font-size:14px;"
        )
        cl.addWidget(self._summary_stmt)
        self._summary_diff = QLabel("Difference: ₹ 0.00")
        self._summary_diff.setStyleSheet(
            f"color:{THEME['accent']}; font-size:16px; font-weight:bold;"
        )
        cl.addWidget(self._summary_diff)
        self._summary_counts = QLabel("")
        self._summary_counts.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        cl.addWidget(self._summary_counts)
        self._summary_notes = QPlainTextEdit()
        self._summary_notes.setPlaceholderText("Notes (optional)")
        self._summary_notes.setFixedHeight(80)
        cl.addWidget(self._summary_notes)
        layout.addWidget(card)

        finalise_row = QHBoxLayout()
        finalise_row.addStretch()
        fb = QPushButton("Finalise reconciliation")
        fb.setObjectName("btn_primary")
        fb.setFixedHeight(40)
        fb.clicked.connect(self._on_finalise)
        finalise_row.addWidget(fb)
        layout.addLayout(finalise_row)
        layout.addStretch()
        return page

    def _go_to_summary(self):
        if self._statement_id is None:
            return
        stmt = self.db.execute(
            "SELECT period_to, statement_closing FROM ledger_statements WHERE id=?",
            (self._statement_id,),
        ).fetchone()
        as_of = stmt["period_to"]
        book = self.reconciler._book_balance(self._ledger_id, as_of)
        stmt_close = stmt["statement_closing"]
        self._summary_book.setText(f"Book balance: ₹ {book:,.2f}")
        if stmt_close is None:
            self._summary_stmt.setText("Statement balance: not detected from import")
            diff = 0.0
        else:
            self._summary_stmt.setText(f"Statement balance: ₹ {stmt_close:,.2f}")
            # MIRROR mode: bank balance from your POV is opposite-signed of theirs.
            # For v1 just compute raw diff and surface it.
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
            self._ledger_id, self._period_from, self._period_to,
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
        self._statement_id = None
        self._refresh_history()
        self._stack.setCurrentWidget(self._setup_page)
