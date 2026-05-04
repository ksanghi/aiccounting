"""
Document Reader page UI.
Drop a file -> extract transactions -> review drafts -> post to ledger.
"""
import json
import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFrame, QFileDialog,
    QProgressBar, QComboBox, QLineEdit, QHeaderView,
    QAbstractItemView, QMessageBox, QCheckBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui  import QColor, QFont

from ui.theme   import THEME, VOUCHER_COLOURS
from ui.widgets import make_label


DOC_TYPES = [
    ("bank_statement",   "Bank Statement"),
    ("sales_invoice",    "Sales Invoice / Bill"),
    ("purchase_invoice", "Purchase Invoice / Bill"),
    ("broker_statement", "Broker / Trading Statement"),
    ("expense_receipt",  "Expense Receipt"),
    ("other",            "Other Document"),
]

_CFG_PATH = Path(__file__).parent.parent / "config" / "display_config.json"


def _load_cfg() -> dict:
    try:
        if _CFG_PATH.exists():
            with open(_CFG_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cfg(data: dict):
    _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_CFG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ── Background worker ─────────────────────────────────────────────────────────

class ProcessThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(list, object)   # vouchers, ExtractionResult
    error    = pyqtSignal(str)

    def __init__(self, filepath, doc_type, api_key, ledger_names, company_name):
        super().__init__()
        self.filepath     = filepath
        self.doc_type     = doc_type
        self.api_key      = api_key
        self.ledger_names = ledger_names
        self.company_name = company_name

    def run(self):
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from ai.document_parser import DocumentParser
            from ai.voucher_ai      import VoucherAI

            self.progress.emit("Reading file…")
            parser = DocumentParser(self.api_key)
            result = parser.parse(self.filepath)

            if not result.success:
                self.error.emit(result.error or "Could not extract text from document.")
                return

            method = result.pages[0].method if result.pages else "unknown"
            self.progress.emit(
                f"Extracted {result.total_pages} page(s) via {method}"
                f" — sending to Claude AI…"
            )

            ai       = VoucherAI(self.api_key)
            vouchers = ai.extract_vouchers(
                result.full_text,
                self.ledger_names,
                self.doc_type,
                self.company_name,
            )

            self.progress.emit(
                f"Found {len(vouchers)} transaction(s) — {result.cost_summary()}"
            )
            self.finished.emit(vouchers, result)

        except Exception as e:
            self.error.emit(str(e))


# ── Drop zone widget ──────────────────────────────────────────────────────────

class DropZone(QFrame):
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)
        self._default_style()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        self._icon = QLabel("📄")
        self._icon.setStyleSheet("font-size:36px;")
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)

        self._lbl = QLabel("Drop any file here or click Browse")
        self._lbl.setStyleSheet(
            f"color:{THEME['text_secondary']};font-size:13px;font-weight:500;"
        )
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lbl)

        fmt = QLabel("PDF  ·  Excel  ·  CSV  ·  JPG  ·  PNG  ·  Word  ·  TXT")
        fmt.setStyleSheet(f"color:{THEME['text_dim']};font-size:10px;")
        fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(fmt)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        browse = QPushButton("Browse File")
        browse.setObjectName("btn_primary")
        browse.setFixedWidth(130)
        browse.setFixedHeight(34)
        browse.clicked.connect(self._browse)
        btn_row.addWidget(browse)
        layout.addLayout(btn_row)

    def _default_style(self):
        self.setStyleSheet(f"""
            QFrame {{
                background:{THEME['bg_card']};
                border:2px dashed {THEME['border']};
                border-radius:12px;
            }}
        """)

    def _hover_style(self):
        self.setStyleSheet(f"""
            QFrame {{
                background:{THEME['accent_dim']};
                border:2px dashed {THEME['accent']};
                border-radius:12px;
            }}
        """)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Document", "",
            "All supported (*.pdf *.xlsx *.xls *.csv *.jpg *.jpeg *.png *.docx *.txt)"
            ";;PDF (*.pdf)"
            ";;Excel (*.xlsx *.xls)"
            ";;CSV (*.csv)"
            ";;Images (*.jpg *.jpeg *.png)"
            ";;Word (*.docx)"
            ";;Text (*.txt)"
        )
        if path:
            self.file_dropped.emit(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hover_style()
            self._lbl.setText("Drop to process")

    def dragLeaveEvent(self, e):
        self._default_style()
        self._lbl.setText("Drop any file here or click Browse")

    def dropEvent(self, e):
        self._default_style()
        self._lbl.setText("Drop any file here or click Browse")
        urls = e.mimeData().urls()
        if urls:
            self.file_dropped.emit(urls[0].toLocalFile())


# ── Main page ─────────────────────────────────────────────────────────────────

class DocumentReaderPage(QWidget):

    def __init__(self, engine, tree, parent=None):
        super().__init__(parent)
        self._engine       = engine
        self._tree         = tree
        self._vouchers     = []
        self._thread       = None
        self._current_file = ""
        self._api_key      = _load_cfg().get("api_key", "")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 24)
        layout.setSpacing(8)

        # Header
        title = QLabel("AI Document Reader")
        title.setObjectName("page_title")
        layout.addWidget(title)

        sub = QLabel(
            "Drop bank statements, invoices, receipts "
            "— AI extracts transactions for your review"
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        # Top row: drop zone + config
        top = QHBoxLayout()
        top.setSpacing(12)

        self._drop = DropZone()
        self._drop.file_dropped.connect(self._on_file_dropped)
        top.addWidget(self._drop, 2)

        cfg_frame = QFrame()
        cfg_frame.setObjectName("card")
        cfg = QVBoxLayout(cfg_frame)
        cfg.setSpacing(10)
        cfg.setContentsMargins(14, 12, 14, 12)

        cfg.addWidget(make_label("Document Type"))
        self._doc_type = QComboBox()
        self._doc_type.setFixedHeight(32)
        for val, label in DOC_TYPES:
            self._doc_type.addItem(label, val)
        cfg.addWidget(self._doc_type)

        cfg.addWidget(make_label("Anthropic API Key"))
        self._api_key_edit = QLineEdit(self._api_key)
        self._api_key_edit.setPlaceholderText("sk-ant-…")
        self._api_key_edit.setFixedHeight(32)
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.textChanged.connect(self._save_api_key)
        cfg.addWidget(self._api_key_edit)

        bal_row = QHBoxLayout()
        bal_lbl = QLabel("Credits:")
        bal_lbl.setStyleSheet(f"color:{THEME['text_secondary']};font-size:11px;")
        self._bal_label = QLabel("Rs.0.00")
        self._bal_label.setStyleSheet(
            f"color:{THEME['success']};font-size:12px;font-weight:bold;"
        )
        demo_btn = QPushButton("Add Demo Rs.50")
        demo_btn.setFixedHeight(28)
        demo_btn.clicked.connect(self._add_demo_credits)
        bal_row.addWidget(bal_lbl)
        bal_row.addWidget(self._bal_label)
        bal_row.addStretch()
        bal_row.addWidget(demo_btn)
        cfg.addLayout(bal_row)

        cfg.addStretch()

        self._process_btn = QPushButton("Process Document")
        self._process_btn.setObjectName("btn_primary")
        self._process_btn.setFixedHeight(36)
        self._process_btn.setEnabled(False)
        self._process_btn.clicked.connect(self._process)
        cfg.addWidget(self._process_btn)

        top.addWidget(cfg_frame, 1)
        layout.addLayout(top)

        # Progress + status
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.setVisible(False)
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background:{THEME['bg_input']};
                border-radius:2px; border:none;
            }}
            QProgressBar::chunk {{
                background:{THEME['accent']};
                border-radius:2px;
            }}
        """)
        layout.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color:{THEME['text_secondary']};font-size:11px;padding:2px 0;"
        )
        layout.addWidget(self._status)

        # Review table
        rev_lbl = QLabel("Review Transactions")
        rev_lbl.setStyleSheet(
            f"font-size:13px;font-weight:bold;"
            f"color:{THEME['text_primary']};padding-top:8px;"
        )
        layout.addWidget(rev_lbl)

        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels([
            "✓", "Date", "Type",
            "Dr Ledger", "Cr Ledger",
            "Amount", "Narration", "Reference", "Conf%"
        ])
        hv = self._table.horizontalHeader()
        col_widths = {0: 30, 1: 95, 2: 90, 5: 110, 7: 100, 8: 60}
        stretch    = {3, 4, 6}
        for c in range(9):
            if c in stretch:
                hv.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
            else:
                hv.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
                self._table.setColumnWidth(c, col_widths.get(c, 80))
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        layout.addWidget(self._table, 1)

        # Footer
        foot = QHBoxLayout()
        sel_all = QPushButton("Select All")
        sel_all.setFixedHeight(32)
        sel_all.clicked.connect(lambda: self._select_all(True))
        sel_none = QPushButton("Deselect All")
        sel_none.setFixedHeight(32)
        sel_none.clicked.connect(lambda: self._select_all(False))
        foot.addWidget(sel_all)
        foot.addWidget(sel_none)
        foot.addStretch()

        self._total_label = QLabel("")
        self._total_label.setStyleSheet(
            f"color:{THEME['text_secondary']};font-size:11px;"
        )
        foot.addWidget(self._total_label)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(
            f"color:{THEME['text_secondary']};font-size:11px;"
        )
        foot.addWidget(self._count_label)

        self._post_btn = QPushButton("Post Selected Vouchers")
        self._post_btn.setObjectName("btn_primary")
        self._post_btn.setFixedHeight(36)
        self._post_btn.setMinimumWidth(180)
        self._post_btn.setEnabled(False)
        self._post_btn.clicked.connect(self._post_selected)
        foot.addWidget(self._post_btn)
        layout.addLayout(foot)

        self._update_balance()

    # ── Config helpers ────────────────────────────────────────────────────────

    def _save_api_key(self, key: str):
        self._api_key = key
        cfg = _load_cfg()
        cfg["api_key"] = key
        _save_cfg(cfg)

    def _add_demo_credits(self):
        from ai.credit_manager import CreditManager
        CreditManager().add_demo_credits()
        self._update_balance()
        QMessageBox.information(
            self, "Credits Added",
            "Rs.50 demo credits added.\n"
            "Covers ~10 AI pages or ~500 local pages."
        )

    def _update_balance(self):
        try:
            from ai.credit_manager import CreditManager
            self._bal_label.setText(CreditManager().balance_display)
        except Exception:
            self._bal_label.setText("Rs.0.00")

    # ── File handling ─────────────────────────────────────────────────────────

    def _on_file_dropped(self, path: str):
        self._current_file = path
        fname = Path(path).name
        self._drop._lbl.setText(f"📄  {fname}")
        self._process_btn.setEnabled(True)

        # Auto-detect document type from filename
        fl = fname.lower()
        if any(x in fl for x in [
            "statement", "bank", "account",
            "hdfc", "axis", "sbi", "icici",
            "union", "kotak", "yes", "indusind",
            "pnb", "boi", "canara", "federal",
        ]):
            self._doc_type.setCurrentIndex(0)
            self._status.setText(
                f"Ready: {fname}  (detected: bank statement)"
            )
        elif any(x in fl for x in [
            "invoice", "bill", "purchase", "vendor",
        ]):
            self._doc_type.setCurrentIndex(2)
            self._status.setText(
                f"Ready: {fname}  (detected: purchase invoice)"
            )
        elif any(x in fl for x in [
            "zerodha", "broker", "contract", "trade",
            "pnl", "profit",
        ]):
            self._doc_type.setCurrentIndex(3)
            self._status.setText(
                f"Ready: {fname}  (detected: broker statement)"
            )
        else:
            self._status.setText(f"Ready to process: {fname}")

    # ── Processing ────────────────────────────────────────────────────────────

    def _process(self):
        if not self._current_file:
            return

        api_key = self._api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(
                self, "API Key Required",
                "Please enter your Anthropic API key in the field above.\n\n"
                "Get one at: console.anthropic.com"
            )
            return

        try:
            ledger_names = [l["name"] for l in self._tree.get_all_ledgers()]
        except Exception:
            ledger_names = []

        try:
            company = self._engine.get_company().get("name", "")
        except Exception:
            company = ""

        self._progress.setVisible(True)
        self._process_btn.setEnabled(False)
        self._status.setText("Processing…")
        self._table.setRowCount(0)
        self._post_btn.setEnabled(False)

        self._thread = ProcessThread(
            self._current_file,
            self._doc_type.currentData(),
            api_key,
            ledger_names,
            company,
        )
        self._thread.progress.connect(self._on_progress)
        self._thread.finished.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _on_progress(self, msg: str):
        self._status.setText(msg)

    def _on_finished(self, vouchers: list, result):
        self._progress.setVisible(False)
        self._process_btn.setEnabled(True)
        self._vouchers = vouchers

        if not vouchers:
            self._status.setText(
                "No transactions found. Try a different document type."
            )
            return

        try:
            from ai.credit_manager import CreditManager
            CreditManager().deduct(
                result.local_pages, result.claude_pages,
                Path(self._current_file).name
            )
            self._update_balance()
        except Exception:
            pass

        self._fill_review_table(vouchers)
        self._status.setText(
            f"Found {len(vouchers)} transaction(s). "
            f"Review and post selected.  {result.cost_summary()}"
        )
        self._post_btn.setEnabled(True)

    def _on_error(self, msg: str):
        self._progress.setVisible(False)
        self._process_btn.setEnabled(True)
        self._status.setText(f"Error: {msg}")
        QMessageBox.critical(self, "Processing Error", msg)

    # ── Review table ──────────────────────────────────────────────────────────

    def _fill_review_table(self, vouchers: list):
        self._table.setRowCount(len(vouchers))
        total_dr = 0.0
        total_cr = 0.0

        for r, v in enumerate(vouchers):
            conf   = float(v.get("confidence", 0))
            vtype  = v.get("voucher_type", "")
            amount = float(v.get("amount", 0))
            dr_ldg = v.get("dr_ledger", "")
            cr_ldg = v.get("cr_ledger", "")

            # Row background based on confidence
            if conf < 0.6:
                row_bg = THEME["danger_dim"]
            elif conf < 0.8:
                row_bg = "#2A1A00"   # amber-dark
            else:
                row_bg = ""

            # Checkbox — pre-check only if confidence is decent
            chk = QCheckBox()
            chk.setChecked(conf >= 0.7)
            chk.stateChanged.connect(self._update_count)
            self._table.setCellWidget(r, 0, chk)

            colour    = VOUCHER_COLOURS.get(vtype, THEME["text_secondary"])
            dr_is_new = "(NEW)" in dr_ldg
            cr_is_new = "(NEW)" in cr_ldg

            vals = [
                v.get("date", ""),
                vtype,
                dr_ldg,
                cr_ldg,
                f"Rs.{amount:,.2f}",
                v.get("narration", "")[:60],
                v.get("reference", ""),
                f"{conf * 100:.0f}%",
            ]

            for c, val in enumerate(vals, 1):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
                )

                # Voucher type in its colour, bold
                if c == 2:
                    item.setForeground(QColor(colour))
                    item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))

                # NEW ledgers in warning orange so user notices
                if c == 3 and dr_is_new:
                    item.setForeground(QColor(THEME["warning"]))
                if c == 4 and cr_is_new:
                    item.setForeground(QColor(THEME["warning"]))

                # Confidence column coloured by threshold
                if c == 8:
                    if conf >= 0.9:
                        item.setForeground(QColor(THEME["success"]))
                    elif conf >= 0.7:
                        item.setForeground(QColor(THEME["warning"]))
                    else:
                        item.setForeground(QColor(THEME["danger"]))

                # Low-confidence row gets a tinted background
                if row_bg:
                    item.setBackground(QColor(row_bg))

                self._table.setItem(r, c, item)

            # Accumulate totals
            if vtype in ("PAYMENT", "PURCHASE", "DEBIT_NOTE"):
                total_dr += amount
            else:
                total_cr += amount

        self._update_count()
        net = abs(total_dr - total_cr)
        self._total_label.setText(
            f"Payments: Rs.{total_dr:,.2f}  |  "
            f"Receipts: Rs.{total_cr:,.2f}  |  "
            f"Net: Rs.{net:,.2f}"
        )

    def _update_count(self):
        selected = sum(
            1 for r in range(self._table.rowCount())
            if (w := self._table.cellWidget(r, 0)) and w.isChecked()
        )
        self._count_label.setText(
            f"{selected} of {self._table.rowCount()} selected"
        )

    def _select_all(self, checked: bool):
        for r in range(self._table.rowCount()):
            w = self._table.cellWidget(r, 0)
            if w:
                w.setChecked(checked)

    # ── Posting ───────────────────────────────────────────────────────────────

    def _post_selected(self):
        from core.voucher_engine import (
            VoucherEngine, VoucherDraft, VoucherLine, VoucherValidationError
        )

        ledger_map = {l["name"]: l["id"] for l in self._tree.get_all_ledgers()}
        engine     = VoucherEngine(self._engine.db, self._engine.company_id)

        posted, skipped, errors = 0, 0, []

        for r in range(self._table.rowCount()):
            chk = self._table.cellWidget(r, 0)
            if not chk or not chk.isChecked():
                continue

            v       = self._vouchers[r]
            vtype   = v.get("voucher_type", "JOURNAL")
            dr_name = v.get("dr_ledger", "").replace(" (NEW)", "").strip()
            cr_name = v.get("cr_ledger", "").replace(" (NEW)", "").strip()
            dr_id   = ledger_map.get(dr_name)
            cr_id   = ledger_map.get(cr_name)

            if not dr_id or not cr_id:
                errors.append(
                    f"Row {r+1}: ledger not found — '{dr_name}' / '{cr_name}'"
                )
                skipped += 1
                continue

            try:
                amount = float(v.get("amount", 0))
                date   = v.get("date", "")
                narr   = v.get("narration", "")
                ref    = v.get("reference", "")

                if vtype == "PAYMENT":
                    draft = engine.build_payment(date, dr_id, cr_id, amount, narr, ref)
                elif vtype == "RECEIPT":
                    draft = engine.build_receipt(date, cr_id, dr_id, amount, narr, ref)
                elif vtype == "CONTRA":
                    draft = engine.build_contra(date, cr_id, dr_id, amount, narr)
                else:
                    draft = VoucherDraft(
                        voucher_type="JOURNAL",
                        voucher_date=date,
                        narration=narr,
                        reference=ref,
                        lines=[
                            VoucherLine(ledger_id=dr_id, dr_amount=amount),
                            VoucherLine(ledger_id=cr_id, cr_amount=amount),
                        ],
                    )

                draft.source = "AI_DOC"
                engine.post(draft)
                posted += 1

            except VoucherValidationError as e:
                errors.append(f"Row {r+1}: {'; '.join(e.errors)}")
                skipped += 1
            except Exception as e:
                errors.append(f"Row {r+1}: {e}")
                skipped += 1

        msg = f"Posted: {posted} voucher(s)\nSkipped: {skipped} voucher(s)"
        if errors:
            msg += "\n\nIssues:\n" + "\n".join(errors[:10])

        if posted > 0:
            QMessageBox.information(self, "Done", msg)
            self._table.setRowCount(0)
            self._vouchers = []
            self._post_btn.setEnabled(False)
            self._status.setText(f"Posted {posted} voucher(s) to ledger.")
        else:
            QMessageBox.warning(self, "Nothing Posted", msg)
