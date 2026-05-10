"""
Book Migration Wizard — 4-step modal dialog.

    Step 1: Pick source format (Tally XML / Excel COA / Zoho-QB CSV)
    Step 2: Pick file (drop or browse)
    Step 3: Dry-run preview — counts + warnings + sample of what will land
    Step 4: Apply — progress + result summary

Used from two surfaces:
  • Company-selector "Import from another system" on new company creation
  • Sidebar "Migration" page in the DATA section

Both surfaces construct the wizard with (db, company_id, tree) for the
target company.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QPlainTextEdit,
    QRadioButton, QButtonGroup, QFileDialog, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal

from ui.theme import THEME
from core.migration import (
    Migrator, MigrationPayload, ValidationResult, ApplyResult, MigrationError,
)


_SOURCES = [
    ("TALLY_XML", "Tally XML",
     "Tally Prime / ERP 9 master export (List of Accounts → Alt+E → XML)"),
    ("EXCEL_COA", "Excel chart of accounts",
     "User-prepared spreadsheet with groups + ledger master"),
    ("CLOUD_CSV", "Zoho Books / QuickBooks CSV",
     "Chart-of-accounts CSV from a cloud accounting app"),
]


class MigrationWizard(QDialog):

    completed = Signal(int)   # run_id on successful apply

    def __init__(self, db, company_id: int, tree, parent=None):
        super().__init__(parent)
        self.db         = db
        self.company_id = company_id
        self.tree       = tree
        self.migrator   = Migrator(db, company_id, tree)

        self._source_type: str = ""
        self._file_path: str = ""
        self._payload: Optional[MigrationPayload] = None
        self._validation: Optional[ValidationResult] = None

        self.setWindowTitle("Book Migration")
        self.setMinimumWidth(720)
        self.setMinimumHeight(560)
        self.setModal(True)
        self._build_ui()

        # Refuse early if target has vouchers
        try:
            self.migrator.check_target_compatible()
        except MigrationError as e:
            QMessageBox.warning(self, "Cannot migrate", str(e))
            self._set_blocked()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("Migrate from another system")
        title.setStyleSheet(
            f"font-size:16px; font-weight:bold; color:{THEME['text_primary']};"
        )
        layout.addWidget(title)
        sub = QLabel(
            "Imports groups + ledger master + opening balances. "
            "Historical transactions stay in your old system; reports in "
            "this app start from the post-migration opening balances."
        )
        sub.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)
        self._stack.addWidget(self._build_step_source())
        self._stack.addWidget(self._build_step_file())
        self._stack.addWidget(self._build_step_preview())
        self._stack.addWidget(self._build_step_done())

        # Footer nav
        self._foot = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._back_btn.clicked.connect(self._go_back)
        self._foot.addWidget(self._back_btn)
        self._foot.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        self._foot.addWidget(self._cancel_btn)
        self._next_btn = QPushButton("Next →")
        self._next_btn.setObjectName("btn_primary")
        self._next_btn.clicked.connect(self._go_next)
        self._foot.addWidget(self._next_btn)
        layout.addLayout(self._foot)

        self._update_nav()

    def _set_blocked(self):
        for btn in (self._next_btn, self._back_btn):
            btn.setEnabled(False)

    def _update_nav(self):
        idx = self._stack.currentIndex()
        self._back_btn.setEnabled(0 < idx < 3)
        self._next_btn.setVisible(idx < 3)
        self._cancel_btn.setText("Close" if idx == 3 else "Cancel")

    def _go_next(self):
        idx = self._stack.currentIndex()
        if idx == 0:
            if not self._source_type:
                QMessageBox.warning(self, "Pick source", "Choose a source format first.")
                return
            self._stack.setCurrentIndex(1)
        elif idx == 1:
            if not self._file_path:
                QMessageBox.warning(self, "Pick file", "Drop or browse to a source file.")
                return
            ok = self._do_parse_and_validate()
            if ok:
                self._stack.setCurrentIndex(2)
        elif idx == 2:
            self._do_apply()
        self._update_nav()

    def _go_back(self):
        idx = self._stack.currentIndex()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
        self._update_nav()

    # ── Step 1: source picker ────────────────────────────────────────────────

    def _build_step_source(self) -> QFrame:
        page = QFrame()
        v = QVBoxLayout(page)
        v.setSpacing(10)
        lbl = QLabel("1. Pick the source format")
        lbl.setStyleSheet(
            f"color:{THEME['accent']}; font-weight:bold; font-size:12px;"
        )
        v.addWidget(lbl)

        self._src_group = QButtonGroup(self)
        for code, name, desc in _SOURCES:
            radio_card = QFrame()
            radio_card.setObjectName("card")
            rh = QVBoxLayout(radio_card)
            rh.setContentsMargins(14, 10, 14, 10)
            r = QRadioButton(name)
            r.setStyleSheet(f"font-size:13px; font-weight:bold;")
            r.toggled.connect(
                lambda checked, c=code: self._on_source_pick(c) if checked else None
            )
            self._src_group.addButton(r)
            rh.addWidget(r)
            d = QLabel(desc)
            d.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:11px; padding-left:24px;"
            )
            d.setWordWrap(True)
            rh.addWidget(d)
            v.addWidget(radio_card)
        v.addStretch()
        return page

    def _on_source_pick(self, code: str):
        self._source_type = code

    # ── Step 2: file picker ──────────────────────────────────────────────────

    def _build_step_file(self) -> QFrame:
        from ui.document_reader_page import DropZone
        page = QFrame()
        v = QVBoxLayout(page)
        v.setSpacing(10)
        lbl = QLabel("2. Pick the file")
        lbl.setStyleSheet(
            f"color:{THEME['accent']}; font-weight:bold; font-size:12px;"
        )
        v.addWidget(lbl)

        self._drop = DropZone()
        self._drop.file_dropped.connect(self._on_file_picked)
        v.addWidget(self._drop)

        self._file_label = QLabel("")
        self._file_label.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:6px;"
        )
        self._file_label.setWordWrap(True)
        v.addWidget(self._file_label)
        v.addStretch()
        return page

    def _on_file_picked(self, path: str):
        self._file_path = path
        self._file_label.setText(f"Selected: {path}")

    # ── Step 3: preview ──────────────────────────────────────────────────────

    def _build_step_preview(self) -> QFrame:
        page = QFrame()
        v = QVBoxLayout(page)
        v.setSpacing(8)
        lbl = QLabel("3. Preview & confirm")
        lbl.setStyleSheet(
            f"color:{THEME['accent']}; font-weight:bold; font-size:12px;"
        )
        v.addWidget(lbl)

        self._preview_summary = QLabel("")
        self._preview_summary.setStyleSheet(
            f"color:{THEME['text_primary']}; font-size:13px;"
        )
        self._preview_summary.setWordWrap(True)
        v.addWidget(self._preview_summary)

        self._preview_table = QTableWidget(0, 4)
        self._preview_table.setHorizontalHeaderLabels(
            ["Ledger", "Group", "Opening", "Dr/Cr"]
        )
        self._preview_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        self._preview_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._preview_table.verticalHeader().setDefaultSectionSize(28)
        v.addWidget(self._preview_table, 1)

        self._warnings_box = QPlainTextEdit()
        self._warnings_box.setReadOnly(True)
        self._warnings_box.setMaximumHeight(110)
        self._warnings_box.setStyleSheet(
            f"background:{THEME['bg_input']}; color:{THEME['warning']}; font-size:11px;"
        )
        v.addWidget(self._warnings_box)
        return page

    def _do_parse_and_validate(self) -> bool:
        try:
            if self._source_type == "EXCEL_COA":
                from core.migration.excel_coa import parse_excel_coa
                self._payload = parse_excel_coa(self._file_path)
            elif self._source_type == "TALLY_XML":
                from core.migration.tally_xml import parse_tally_xml
                self._payload = parse_tally_xml(self._file_path)
            elif self._source_type == "CLOUD_CSV":
                from core.migration.cloud_csv import parse_cloud_csv
                self._payload = parse_cloud_csv(self._file_path)
            else:
                QMessageBox.critical(self, "Internal", f"Unknown source type {self._source_type}")
                return False
        except Exception as e:
            QMessageBox.critical(self, "Could not parse", str(e))
            return False

        v = self.migrator.validate(self._payload)
        self._validation = v

        c = v.counts
        self._preview_summary.setText(
            f"<b>{c['ledgers']} ledger(s)</b> in "
            f"<b>{c['groups']} new group(s)</b>  ·  "
            f"Opening Dr: ₹{c['opening_total_dr']:,.2f}  ·  "
            f"Opening Cr: ₹{c['opening_total_cr']:,.2f}  ·  "
            f"diff ₹{c['opening_diff']:+,.2f}"
        )

        # Sample table — first 200 ledgers
        self._preview_table.setRowCount(0)
        for ld in self._payload.ledgers[:200]:
            r = self._preview_table.rowCount()
            self._preview_table.insertRow(r)
            self._preview_table.setItem(r, 0, QTableWidgetItem(ld.name))
            self._preview_table.setItem(r, 1, QTableWidgetItem(ld.group_name))
            self._preview_table.setItem(r, 2, QTableWidgetItem(
                f"₹ {ld.opening_balance:,.2f}"
            ))
            self._preview_table.setItem(r, 3, QTableWidgetItem(ld.opening_type))

        msgs = []
        if v.warnings:
            msgs.append("WARNINGS:")
            msgs.extend(f"  • {w}" for w in v.warnings)
        if self._payload.notes:
            msgs.append("PARSER NOTES:")
            msgs.extend(f"  • {n}" for n in self._payload.notes)
        if v.errors:
            msgs.insert(0, "ERRORS (must fix before applying):")
            for e in v.errors:
                msgs.insert(1, f"  • {e}")
            self._warnings_box.setStyleSheet(
                f"background:{THEME['bg_input']}; color:{THEME['danger']}; font-size:11px;"
            )
        else:
            self._warnings_box.setStyleSheet(
                f"background:{THEME['bg_input']}; color:{THEME['warning']}; font-size:11px;"
            )

        self._warnings_box.setPlainText("\n".join(msgs) or "No issues detected.")
        # Disable Apply if errors
        self._next_btn.setText(
            "Apply migration" if v.ok else "(fix errors to apply)"
        )
        self._next_btn.setEnabled(v.ok)
        return True

    # ── Step 4: done ─────────────────────────────────────────────────────────

    def _build_step_done(self) -> QFrame:
        page = QFrame()
        v = QVBoxLayout(page)
        v.setSpacing(10)
        self._done_lbl = QLabel("")
        self._done_lbl.setStyleSheet(
            f"color:{THEME['success']}; font-size:14px; font-weight:bold;"
        )
        v.addWidget(self._done_lbl)
        self._done_detail = QPlainTextEdit()
        self._done_detail.setReadOnly(True)
        v.addWidget(self._done_detail, 1)
        return page

    def _do_apply(self):
        if not self._payload:
            return
        try:
            res: ApplyResult = self.migrator.apply(self._payload)
        except MigrationError as e:
            QMessageBox.critical(self, "Migration failed", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Migration failed", str(e))
            return

        c = res.counts
        self._done_lbl.setText(f"✓ Migration complete (run #{res.run_id})")
        lines = [
            f"Groups added:   {c.get('groups_added', 0)}",
            f"Ledgers added:  {c.get('ledgers_added', 0)}",
            f"Opening diff:   ₹ {c.get('opening_diff', 0):+,.2f}",
        ]
        skipped = c.get("skipped") or []
        if skipped:
            lines.append("")
            lines.append(f"Skipped ({len(skipped)}):")
            lines.extend(f"  • {s}" for s in skipped[:30])
            if len(skipped) > 30:
                lines.append(f"  ... and {len(skipped) - 30} more")
        warnings = c.get("warnings") or []
        if warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.extend(f"  • {w}" for w in warnings)
        if res.errors:
            lines.append("")
            lines.append("Errors during apply:")
            lines.extend(f"  • {e}" for e in res.errors)
        self._done_detail.setPlainText("\n".join(lines))

        self.completed.emit(res.run_id)
        self._stack.setCurrentIndex(3)
