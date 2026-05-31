"""
Book Migration Wizard — 4-step modal dialog.

    Step 1: Pick source format
              (Tally HTTP / Tally XML / Excel COA / Zoho-QB CSV)
    Step 2: Configure source
              (Tally HTTP → host/port/company/date range;
               other sources → file picker)
    Step 3: Dry-run preview — counts + warnings + sample of what will land
    Step 4: Apply — progress + result summary

Used from two surfaces:
  • Company-selector "Import from another system" on new company creation
  • Sidebar "Migration" page in the DATA section

Both surfaces construct the wizard with (db, company_id, tree) for the
target company.

Tally HTTP source pulls ledgers + groups + vouchers in one go, idempotent
on re-run via the (voucher_type, voucher_number) unique constraint.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QPlainTextEdit,
    QRadioButton, QButtonGroup, QFileDialog, QSizePolicy,
    QLineEdit, QComboBox, QDateEdit, QFormLayout,
)
from PySide6.QtCore import Qt, Signal, QDate

from ui.theme import THEME
from core.migration import (
    Migrator, MigrationPayload, ValidationResult, ApplyResult, MigrationError,
)


_SOURCES = [
    ("TALLY_HTTP", "Tally — live via HTTP",
     "Pulls ledgers + vouchers directly from a running Tally Prime / ERP 9 "
     "(release 5+). One-time setup in Tally: F1 → Settings → Connectivity → "
     "HTTP-XML server ON, port 9000."),
    ("TALLY_XML", "Tally XML",
     "Tally Prime / ERP 9 master export (List of Accounts → Alt+E → XML). "
     "Chart of accounts only — no vouchers."),
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

        # Tally HTTP connect state — only populated when that source is picked
        self._tally_host: str = "localhost"
        self._tally_port: int = 9000
        self._tally_company: str = ""
        self._tally_from: Optional[date] = None
        self._tally_to: Optional[date] = None

        self.setWindowTitle("Book Migration")
        self.setMinimumWidth(720)
        self.setMinimumHeight(560)
        self.setModal(True)
        self._build_ui()

        # Target-compat check is deferred until source is picked — the
        # "no vouchers" rule applies to file-based sources, NOT to the
        # idempotent Tally HTTP source (which dedupes on re-run).

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
            # File-based sources: enforce empty-book rule here, late enough
            # that we know the source isn't TALLY_HTTP.
            if self._source_type != "TALLY_HTTP":
                try:
                    self.migrator.check_target_compatible()
                except MigrationError as e:
                    QMessageBox.warning(self, "Cannot migrate", str(e))
                    return
            # Step 2 has two sub-pages — switch based on source type.
            self._step_file_stack.setCurrentIndex(
                1 if self._source_type == "TALLY_HTTP" else 0
            )
            self._stack.setCurrentIndex(1)
        elif idx == 1:
            if self._source_type == "TALLY_HTTP":
                if not self._tally_company:
                    QMessageBox.warning(
                        self, "Pick company",
                        "Probe Tally and select a company first."
                    )
                    return
                if not self._tally_from or not self._tally_to:
                    QMessageBox.warning(
                        self, "Pick dates",
                        "Set a From and To date for the voucher pull."
                    )
                    return
            else:
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

    # ── Step 2: configure source ─────────────────────────────────────────────

    def _build_step_file(self) -> QFrame:
        """Step 2 is a stack with two pages — file picker for file-based
        sources, Tally connect panel for TALLY_HTTP. The outer step shell
        provides the heading; the inner stack swaps based on source."""
        page = QFrame()
        v = QVBoxLayout(page)
        v.setSpacing(10)
        lbl = QLabel("2. Configure source")
        lbl.setStyleSheet(
            f"color:{THEME['accent']}; font-weight:bold; font-size:12px;"
        )
        v.addWidget(lbl)

        self._step_file_stack = QStackedWidget()
        self._step_file_stack.addWidget(self._build_file_picker_page())
        self._step_file_stack.addWidget(self._build_tally_connect_page())
        v.addWidget(self._step_file_stack, 1)
        return page

    def _build_file_picker_page(self) -> QFrame:
        from ui.document_reader_page import DropZone
        page = QFrame()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # Migration accepts all three file source formats — XML (Tally),
        # Excel, and CSV. A single permissive filter avoids needing to
        # recreate the widget when the user changes their step-1 source.
        self._drop = DropZone(
            file_filter=(
                "All migration files (*.xml *.xlsx *.xls *.csv)"
                ";;Tally XML (*.xml)"
                ";;Excel (*.xlsx *.xls)"
                ";;CSV (*.csv)"
                ";;All Files (*)"
            ),
            format_hint="Tally XML  ·  Excel  ·  CSV",
        )
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

    def _build_tally_connect_page(self) -> QFrame:
        page = QFrame()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        hint = QLabel(
            "Tally must be running with the company loaded. The HTTP-XML "
            "server toggle is one-time:  F1 → Settings → Connectivity → "
            "HTTP-XML server ON, port 9000."
        )
        hint.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        hint.setWordWrap(True)
        v.addWidget(hint)

        # Host/port + Probe
        conn_row = QHBoxLayout()
        self._tally_host_edit = QLineEdit(self._tally_host)
        self._tally_host_edit.setPlaceholderText("Host (default: localhost)")
        self._tally_host_edit.setFixedWidth(220)
        self._tally_port_edit = QLineEdit(str(self._tally_port))
        self._tally_port_edit.setPlaceholderText("Port")
        self._tally_port_edit.setFixedWidth(80)
        self._tally_probe_btn = QPushButton("Probe Tally")
        self._tally_probe_btn.clicked.connect(self._on_probe_tally)
        conn_row.addWidget(QLabel("Host:"))
        conn_row.addWidget(self._tally_host_edit)
        conn_row.addWidget(QLabel("Port:"))
        conn_row.addWidget(self._tally_port_edit)
        conn_row.addWidget(self._tally_probe_btn)
        conn_row.addStretch()
        v.addLayout(conn_row)

        self._tally_probe_status = QLabel("Not probed yet.")
        self._tally_probe_status.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        v.addWidget(self._tally_probe_status)

        # Company + date range (disabled until probe succeeds)
        form = QFormLayout()
        self._tally_company_combo = QComboBox()
        self._tally_company_combo.setEnabled(False)
        self._tally_company_combo.currentTextChanged.connect(self._on_company_pick)
        form.addRow("Company:", self._tally_company_combo)

        # Default range: current Indian FY (Apr 1 → today)
        today = date.today()
        fy_start_year = today.year if today.month >= 4 else today.year - 1
        default_from = date(fy_start_year, 4, 1)

        self._tally_from_edit = QDateEdit()
        self._tally_from_edit.setCalendarPopup(True)
        self._tally_from_edit.setDate(QDate(default_from.year, default_from.month, default_from.day))
        self._tally_from_edit.setEnabled(False)
        self._tally_from_edit.dateChanged.connect(self._on_date_change)
        form.addRow("From date:", self._tally_from_edit)

        self._tally_to_edit = QDateEdit()
        self._tally_to_edit.setCalendarPopup(True)
        self._tally_to_edit.setDate(QDate(today.year, today.month, today.day))
        self._tally_to_edit.setEnabled(False)
        self._tally_to_edit.dateChanged.connect(self._on_date_change)
        form.addRow("To date:", self._tally_to_edit)

        v.addLayout(form)
        v.addStretch()
        return page

    def _on_probe_tally(self):
        try:
            from core.migration import tally_http
        except ImportError as e:
            QMessageBox.critical(self, "Internal", f"Tally HTTP module missing: {e}")
            return

        host = (self._tally_host_edit.text() or "localhost").strip()
        try:
            port = int(self._tally_port_edit.text() or "9000")
        except ValueError:
            QMessageBox.warning(self, "Bad port", "Port must be a number.")
            return

        self._tally_probe_btn.setEnabled(False)
        self._tally_probe_status.setText("Probing…")
        # Force the label to repaint before the (potentially-blocking) request
        self._tally_probe_status.repaint()
        try:
            companies = tally_http.list_companies(host=host, port=port, timeout=10)
        except tally_http.TallyHTTPError as e:
            self._tally_probe_status.setStyleSheet(
                f"color:{THEME['danger']}; font-size:11px;"
            )
            self._tally_probe_status.setText(f"Not reachable: {e}")
            self._tally_company_combo.setEnabled(False)
            self._tally_company_combo.clear()
            self._tally_from_edit.setEnabled(False)
            self._tally_to_edit.setEnabled(False)
            return
        finally:
            self._tally_probe_btn.setEnabled(True)

        self._tally_host = host
        self._tally_port = port
        if not companies:
            self._tally_probe_status.setStyleSheet(
                f"color:{THEME['warning']}; font-size:11px;"
            )
            self._tally_probe_status.setText(
                "Tally is up but no company is loaded. Open the source "
                "company in Tally, then probe again."
            )
            self._tally_company_combo.setEnabled(False)
            return

        self._tally_probe_status.setStyleSheet(
            f"color:{THEME['success']}; font-size:11px;"
        )
        self._tally_probe_status.setText(
            f"Connected — {len(companies)} company(s) loaded."
        )
        self._tally_company_combo.clear()
        self._tally_company_combo.addItems(companies)
        self._tally_company_combo.setEnabled(True)
        self._tally_from_edit.setEnabled(True)
        self._tally_to_edit.setEnabled(True)
        # Trigger initial value capture
        self._on_company_pick(self._tally_company_combo.currentText())
        self._on_date_change()

    def _on_company_pick(self, name: str):
        self._tally_company = (name or "").strip()

    def _on_date_change(self):
        q1 = self._tally_from_edit.date()
        q2 = self._tally_to_edit.date()
        self._tally_from = date(q1.year(), q1.month(), q1.day())
        self._tally_to = date(q2.year(), q2.month(), q2.day())

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
            elif self._source_type == "TALLY_HTTP":
                from core.migration import tally_http
                self._payload = tally_http.pull(
                    company=self._tally_company,
                    fy_from=self._tally_from,
                    fy_to=self._tally_to,
                    host=self._tally_host,
                    port=self._tally_port,
                )
            else:
                QMessageBox.critical(self, "Internal", f"Unknown source type {self._source_type}")
                return False
        except Exception as e:
            QMessageBox.critical(self, "Could not parse", str(e))
            return False

        v = self.migrator.validate(self._payload)
        self._validation = v

        c = v.counts
        summary = (
            f"<b>{c['ledgers']} ledger(s)</b> in "
            f"<b>{c['groups']} new group(s)</b>  ·  "
            f"Opening Dr: ₹{c['opening_total_dr']:,.2f}  ·  "
            f"Opening Cr: ₹{c['opening_total_cr']:,.2f}  ·  "
            f"diff ₹{c['opening_diff']:+,.2f}"
        )

        # If vouchers are also in the payload, validate them and append
        # to summary + warnings.
        self._vouch_validation: Optional[ValidationResult] = None
        if self._payload.vouchers:
            vv = self.migrator.validate_vouchers(self._payload)
            self._vouch_validation = vv
            vc = vv.counts
            dr = vc.get("date_range") or ["", ""]
            by_type = vc.get("by_type") or {}
            type_str = ", ".join(f"{k}:{v}" for k, v in sorted(by_type.items()))
            summary += (
                f"<br><b>{vc['vouchers']} voucher(s)</b>"
                f" ({dr[0]} → {dr[1]})  ·  {type_str}"
            )
            if vv.warnings:
                v.warnings.extend(vv.warnings)

        self._preview_summary.setText(summary)

        # Sample table — first 200 ledgers
        self._preview_table.setSortingEnabled(False)
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
        from ui.table_utils import make_sortable as _ms
        _ms(self._preview_table)

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

        # Detect re-run: if vouchers already exist for this company AND the
        # source is TALLY_HTTP, skip the CoA apply (re-running it would
        # error on duplicate ledger names) and only apply vouchers.
        row = self.db.execute(
            "SELECT COUNT(*) AS c FROM vouchers WHERE company_id=?",
            (self.company_id,),
        ).fetchone()
        is_rerun = bool(row and row["c"])

        coa_res: Optional[ApplyResult] = None
        vch_res: Optional[ApplyResult] = None

        try:
            if not is_rerun:
                coa_res = self.migrator.apply(self._payload)
            if self._payload.vouchers:
                vch_res = self.migrator.apply_vouchers(self._payload)
        except MigrationError as e:
            QMessageBox.critical(self, "Migration failed", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Migration failed", str(e))
            return

        run_id = (vch_res.run_id if vch_res else 0) or (coa_res.run_id if coa_res else 0)
        self._done_lbl.setText(f"✓ Migration complete (run #{run_id})")

        lines: list[str] = []
        if coa_res:
            c = coa_res.counts
            lines += [
                f"Groups added:   {c.get('groups_added', 0)}",
                f"Ledgers added:  {c.get('ledgers_added', 0)}",
                f"Opening diff:   ₹ {c.get('opening_diff', 0):+,.2f}",
            ]
            skipped = c.get("skipped") or []
            if skipped:
                lines += ["", f"Ledger rows skipped ({len(skipped)}):"]
                lines += [f"  • {s}" for s in skipped[:20]]
                if len(skipped) > 20:
                    lines.append(f"  ... and {len(skipped) - 20} more")
            warnings = c.get("warnings") or []
            if warnings:
                lines += ["", "Warnings:"]
                lines += [f"  • {w}" for w in warnings]
            if coa_res.errors:
                lines += ["", "Errors during ledger apply:"]
                lines += [f"  • {e}" for e in coa_res.errors]
        elif is_rerun:
            lines.append("Chart of accounts skipped (re-run — already in place).")

        if vch_res:
            vc = vch_res.counts
            lines += [
                "",
                f"Vouchers in payload:  {vc.get('vouchers_in_payload', 0)}",
                f"Vouchers added:       {vc.get('vouchers_added', 0)}",
                f"Duplicates skipped:   {vc.get('duplicate', 0)}",
            ]
            vskipped = vc.get("skipped") or []
            if vskipped:
                lines += ["", f"Vouchers skipped ({len(vskipped)}):"]
                lines += [f"  • {s}" for s in vskipped[:30]]
                if len(vskipped) > 30:
                    lines.append(f"  ... and {len(vskipped) - 30} more")
            if vch_res.errors:
                lines += ["", "Errors during voucher apply:"]
                lines += [f"  • {e}" for e in vch_res.errors]

        self._done_detail.setPlainText("\n".join(lines))

        self.completed.emit(run_id)
        self._stack.setCurrentIndex(3)
