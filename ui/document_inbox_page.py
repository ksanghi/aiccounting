"""
Document Inbox page — the review-and-process queue (the hub).

ONE watched folder feeds this queue (email reader, ADF scanner, manual
drop all land in it). The accountant works the queue top-down:

    pick a doc -> AI classifies it (what is it?) -> they eyeball it on
    screen and confirm/override the type -> APPROVE gates the extraction
    -> AI extracts -> draft voucher(s) -> Post.

The heavy lifting reuses the existing, proven pipeline:
  ai/doc_classifier.py     — the classify step (BYOK)
  ai/document_parser.py    — text extraction
  ai/voucher_ai.py         — document -> draft vouchers
  ui/document_reader_page  — ProcessThread (extract worker) + post logic

This is a PRO/PREMIUM, bring-your-own-key feature (`document_inbox`).
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QFrame, QFileDialog, QComboBox,
    QHeaderView, QAbstractItemView, QMessageBox, QPlainTextEdit, QCheckBox,
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QColor, QDesktopServices

from ui.theme import THEME, VOUCHER_COLOURS
from ui.widgets import make_label
from core import doc_inbox
from core.doc_inbox import DocInbox
from core import email_fetcher as ef
from ai.doc_classifier import DOC_TYPES as _CLS_TYPES

# Human labels for the six classifier doc-types (queue + override combo).
DOC_TYPE_LABELS = {
    "purchase_invoice": "Purchase Invoice",
    "sales_invoice":    "Sales Invoice",
    "debit_note":       "Debit Note",
    "credit_note":      "Credit Note",
    "bank_statement":   "Bank Statement",
    "other":            "Other / Hold",
}
_STATUS_COLOURS = {
    "PENDING":    THEME["text_secondary"],
    "CLASSIFIED": THEME["warning"],
    "APPROVED":   THEME["accent"],
    "POSTED":     THEME["success"],
    "REJECTED":   THEME["text_dim"],
    "ERROR":      THEME["danger"],
}


# ── Background workers ────────────────────────────────────────────────────────

class ProcessThread(QThread):
    """ONE pass: parse the file to text, then a single AI call that BOTH
    classifies and extracts (ai.voucher_ai.extract_auto). The accountant
    reads the doc once, the AI reads it once — no separate classify call.
    Runs on the customer's own (BYOK) key."""
    done  = Signal(int, dict, object)   # doc_id, auto-result, ExtractionResult
    error = Signal(int, str)

    def __init__(self, doc_id: int, filepath: str, ledger_names: list,
                 company_name: str):
        super().__init__()
        self.doc_id = doc_id
        self.filepath = filepath
        self.ledger_names = ledger_names
        self.company_name = company_name

    def run(self):
        try:
            from ai.document_parser import DocumentParser
            from ai.voucher_ai import VoucherAI
            result = DocumentParser().parse(self.filepath)
            if not result.success:
                self.error.emit(self.doc_id,
                                result.error or "Could not read the document.")
                return
            auto = VoucherAI().extract_auto(
                result.full_text, self.ledger_names, self.company_name
            )
            self.done.emit(self.doc_id, auto, result)
        except Exception as e:
            self.error.emit(self.doc_id, str(e))


class EmailFetchThread(QThread):
    """Pull new attachments from the customer's mailbox (read-only, IMAP).
    Blocking network I/O — runs off the UI thread. Returns the staged files
    + their email metadata + the cfg (with advanced last_uid) for the page
    to ingest and persist."""
    done  = Signal(int, list, object)   # scanned, saved[], cfg
    error = Signal(str)

    def __init__(self, cfg, dest_dir: str):
        super().__init__()
        self.cfg = cfg
        self.dest_dir = dest_dir

    def run(self):
        try:
            scanned, saved = ef.fetch_new(self.cfg, self.dest_dir)
            self.done.emit(scanned, saved, self.cfg)
        except Exception as e:
            self.error.emit(str(e))


# ── Main page ─────────────────────────────────────────────────────────────────

class DocumentInboxPage(QWidget):

    def __init__(self, engine, tree, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._tree = tree
        self._conn = engine.db.connect()
        try:
            self._company_name = engine.get_company().get("name", "") or "company"
        except Exception:
            self._company_name = "company"
        self._inbox = DocInbox(self._conn, engine.company_id, self._company_name)
        self._proc_thread = None
        self._email_thread = None
        self._current_id = None
        self._drafts = []
        self._build_ui()
        self.refresh()
        self._update_email_button()
        # Auto-poll the mailbox every 5 minutes while this page exists, but
        # only if the user enabled it in the email settings.
        self._email_timer = QTimer(self)
        self._email_timer.setInterval(5 * 60 * 1000)
        self._email_timer.timeout.connect(self._auto_poll_email)
        self._email_timer.start()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 24)
        layout.setSpacing(8)

        title = QLabel("Document Inbox")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel(
            "Invoices, debit/credit notes and statements arrive here from "
            "email & scanner — AI sorts each, you approve, it posts."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        # Toolbar
        bar = QHBoxLayout()
        scan_btn = QPushButton("⟳  Scan Folder")
        scan_btn.setFixedHeight(30)
        scan_btn.setToolTip("Pick up new files dropped/scanned into the inbox folder")
        scan_btn.clicked.connect(self._scan_folder)
        add_btn = QPushButton("＋  Add Files")
        add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self._add_files)
        open_btn = QPushButton("📂  Open Inbox Folder")
        open_btn.setFixedHeight(30)
        open_btn.clicked.connect(self._open_folder)
        self._email_btn = QPushButton("📧  Check Email")
        self._email_btn.setFixedHeight(30)
        self._email_btn.setToolTip("Pull new invoice attachments from your mailbox")
        self._email_btn.clicked.connect(self._email_clicked)
        email_setup_btn = QPushButton("⚙")
        email_setup_btn.setFixedHeight(30)
        email_setup_btn.setFixedWidth(34)
        email_setup_btn.setToolTip("Email connection settings")
        email_setup_btn.clicked.connect(self._open_email_setup)
        bar.addWidget(scan_btn)
        bar.addWidget(add_btn)
        bar.addWidget(open_btn)
        bar.addWidget(self._email_btn)
        bar.addWidget(email_setup_btn)
        bar.addStretch()
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(
            f"color:{THEME['text_secondary']};font-size:11px;"
        )
        bar.addWidget(self._count_lbl)
        layout.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)

        # Left — queue
        self._queue = QTableWidget()
        self._queue.setColumnCount(4)
        self._queue.setHorizontalHeaderLabels(["Document", "Type", "Status", "Conf"])
        qh = self._queue.horizontalHeader()
        qh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c, w in {1: 120, 2: 90, 3: 55}.items():
            qh.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self._queue.setColumnWidth(c, w)
        self._queue.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._queue.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._queue.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._queue.verticalHeader().setVisible(False)
        self._queue.setShowGrid(False)
        self._queue.setAlternatingRowColors(True)
        self._queue.itemSelectionChanged.connect(self._on_select)
        split.addWidget(self._queue)

        # Right — detail
        detail = QFrame()
        detail.setObjectName("card")
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(16, 14, 16, 14)
        dl.setSpacing(10)

        self._name_lbl = QLabel("Select a document")
        self._name_lbl.setStyleSheet(
            f"font-size:14px;font-weight:bold;color:{THEME['text_primary']};"
        )
        self._name_lbl.setWordWrap(True)
        dl.addWidget(self._name_lbl)

        self._ai_lbl = QLabel("")
        self._ai_lbl.setWordWrap(True)
        self._ai_lbl.setStyleSheet(
            f"color:{THEME['text_secondary']};font-size:11px;"
        )
        dl.addWidget(self._ai_lbl)

        # Type override
        type_row = QHBoxLayout()
        type_row.addWidget(make_label("Document type"))
        self._type_combo = QComboBox()
        self._type_combo.setFixedHeight(30)
        for key in _CLS_TYPES:
            self._type_combo.addItem(DOC_TYPE_LABELS.get(key, key), key)
        type_row.addWidget(self._type_combo, 1)
        dl.addLayout(type_row)

        # Action buttons
        act_row = QHBoxLayout()
        self._open_doc_btn = QPushButton("👁  View Document")
        self._open_doc_btn.setFixedHeight(32)
        self._open_doc_btn.clicked.connect(self._view_document)
        self._process_btn = QPushButton("⚡  Process with AI")
        self._process_btn.setObjectName("btn_primary")
        self._process_btn.setFixedHeight(32)
        self._process_btn.setToolTip(
            "One AI pass on your own key — reads the document, decides its "
            "type, and drafts the voucher(s) for you to accept or reject."
        )
        self._process_btn.clicked.connect(self._process)
        self._reject_btn = QPushButton("✕  Reject")
        self._reject_btn.setFixedHeight(32)
        self._reject_btn.clicked.connect(self._reject)
        act_row.addWidget(self._open_doc_btn)
        act_row.addWidget(self._process_btn)
        act_row.addWidget(self._reject_btn)
        dl.addLayout(act_row)

        self._detail_status = QLabel("")
        self._detail_status.setWordWrap(True)
        self._detail_status.setStyleSheet(
            f"color:{THEME['text_secondary']};font-size:11px;"
        )
        dl.addWidget(self._detail_status)

        # Draft review table (after extraction)
        dl.addWidget(make_label("Extracted draft(s)"))
        self._drafts_tbl = QTableWidget()
        self._drafts_tbl.setColumnCount(7)
        self._drafts_tbl.setHorizontalHeaderLabels(
            ["✓", "Date", "Type", "Dr", "Cr", "Amount", "Conf"]
        )
        dh = self._drafts_tbl.horizontalHeader()
        dh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        dh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for c, w in {0: 28, 1: 85, 2: 80, 5: 95, 6: 50}.items():
            dh.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self._drafts_tbl.setColumnWidth(c, w)
        self._drafts_tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._drafts_tbl.verticalHeader().setVisible(False)
        self._drafts_tbl.setShowGrid(False)
        dl.addWidget(self._drafts_tbl, 1)

        self._post_btn = QPushButton("✓  Accept & Post Selected")
        self._post_btn.setObjectName("btn_primary")
        self._post_btn.setFixedHeight(34)
        self._post_btn.setEnabled(False)
        self._post_btn.clicked.connect(self._post)
        dl.addWidget(self._post_btn)

        split.addWidget(detail)
        split.setSizes([420, 520])
        layout.addWidget(split, 1)

        self._set_detail_enabled(False)

    # ── Queue ───────────────────────────────────────────────────────────────
    def refresh(self):
        docs = self._inbox.list()
        self._queue.setRowCount(len(docs))
        self._rows = docs
        for r, d in enumerate(docs):
            name = QTableWidgetItem(d["stored_name"])
            name.setData(Qt.ItemDataRole.UserRole, d["id"])
            self._queue.setItem(r, 0, name)

            dt = d.get("doc_type")
            self._queue.setItem(
                r, 1, QTableWidgetItem(DOC_TYPE_LABELS.get(dt, "—") if dt else "—")
            )
            st = QTableWidgetItem(d["status"])
            st.setForeground(QColor(_STATUS_COLOURS.get(d["status"], THEME["text_primary"])))
            self._queue.setItem(r, 2, st)

            conf = d.get("ai_confidence")
            self._queue.setItem(
                r, 3, QTableWidgetItem(f"{conf*100:.0f}%" if conf else "")
            )
        pend = self._inbox.pending_count()
        self._count_lbl.setText(
            f"{pend} awaiting review  ·  {len(docs)} total"
        )

    def _selected_doc(self) -> dict | None:
        rows = self._queue.selectionModel().selectedRows()
        if not rows:
            return None
        item = self._queue.item(rows[0].row(), 0)
        doc_id = item.data(Qt.ItemDataRole.UserRole)
        return self._inbox.get(doc_id)

    def _on_select(self):
        doc = self._selected_doc()
        self._drafts_tbl.setRowCount(0)
        self._drafts = []
        self._post_btn.setEnabled(False)
        if not doc:
            self._set_detail_enabled(False)
            self._name_lbl.setText("Select a document")
            self._ai_lbl.setText("")
            return
        self._current_id = doc["id"]
        self._set_detail_enabled(
            doc["status"] in ("PENDING", "CLASSIFIED", "APPROVED", "ERROR")
        )
        self._name_lbl.setText(doc["stored_name"])

        dt = doc.get("doc_type") or "other"
        idx = self._type_combo.findData(dt)
        self._type_combo.setCurrentIndex(max(0, idx))

        # No AI on select — the accountant reads the doc, then clicks
        # "Process with AI" (one call) when ready. This avoids spending the
        # customer's key just to browse the queue.
        self._render_ai_summary(doc)

    def _render_ai_summary(self, doc: dict):
        meta = {}
        try:
            meta = json.loads(doc.get("ai_meta") or "{}")
        except Exception:
            meta = {}
        if doc["status"] == "POSTED":
            self._ai_lbl.setText("✓ Posted to the books.")
            return
        if doc["status"] == "REJECTED":
            self._ai_lbl.setText("Rejected — not posted.")
            return
        if doc["status"] == "ERROR" and doc.get("error"):
            self._ai_lbl.setText(f"⚠ {doc['error']}")
            return
        if doc["status"] == "PENDING":
            self._ai_lbl.setText(
                "Open it with “View Document”, then “Process with AI” to "
                "draft the voucher(s)."
            )
            return
        # CLASSIFIED/APPROVED — show the summary the single pass produced.
        line = []
        for k, lbl in (("party", "Party"), ("doc_number", "No"),
                       ("doc_date", "Date"), ("amount", "Amount")):
            v = meta.get(k)
            if v:
                line.append(f"{lbl}: {v}")
        self._ai_lbl.setText("   ·   ".join(line) if line
                             else "Processed — review the drafts below.")

    def _set_detail_enabled(self, on: bool):
        for w in (self._type_combo, self._process_btn, self._reject_btn,
                  self._open_doc_btn):
            w.setEnabled(on)

    # ── Ingest actions ──────────────────────────────────────────────────────
    def _scan_folder(self):
        n = self._inbox.scan_incoming()
        self.refresh()
        self._count_lbl.setText(
            f"Picked up {n} new file(s)." if n else "No new files in the inbox folder."
        )

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add documents to the inbox", "",
            "Documents (*.pdf *.jpg *.jpeg *.png *.xlsx *.xls *.csv *.docx *.txt)",
        )
        added = 0
        for p in paths:
            if self._inbox.ingest_file(p, source=doc_inbox.SOURCE_MANUAL):
                added += 1
        self.refresh()
        if paths:
            self._count_lbl.setText(f"Added {added} of {len(paths)} file(s).")

    def _open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._inbox.store_dir)))

    def _view_document(self):
        doc = self._selected_doc()
        if doc and Path(doc["stored_path"]).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(doc["stored_path"]))

    # ── Email feeder ────────────────────────────────────────────────────────
    def _email_configured(self) -> bool:
        c = ef.load_config(self._inbox.slug)
        return bool(c.email and c.host and c.password)

    def _update_email_button(self):
        if self._email_configured():
            c = ef.load_config(self._inbox.slug)
            self._email_btn.setText("📧  Check Email")
            self._email_btn.setToolTip(f"Pull new attachments from {c.email}")
        else:
            self._email_btn.setText("📧  Connect Email")
            self._email_btn.setToolTip("Set up your mailbox to auto-import invoices")

    def _open_email_setup(self):
        from ui.email_setup_dialog import EmailSetupDialog
        dlg = EmailSetupDialog(self._inbox.slug, self)
        if dlg.exec():
            self._update_email_button()
            if getattr(dlg, "fetch_after", False):
                self._fetch_email(manual=True)

    def _email_clicked(self):
        if self._email_configured():
            self._fetch_email(manual=True)
        else:
            self._open_email_setup()

    def _auto_poll_email(self):
        c = ef.load_config(self._inbox.slug)
        if c.enabled and c.email and c.host and c.password:
            self._fetch_email(manual=False)

    def _fetch_email(self, manual: bool):
        if self._email_thread and self._email_thread.isRunning():
            return
        cfg = ef.load_config(self._inbox.slug)
        if not (cfg.email and cfg.host and cfg.password):
            if manual:
                self._open_email_setup()
            return
        self._email_btn.setEnabled(False)
        self._count_lbl.setText("Checking mailbox…")
        self._email_thread = EmailFetchThread(cfg, str(self._inbox.incoming_dir))
        self._email_thread.done.connect(
            lambda scanned, saved, c: self._on_email_fetched(scanned, saved, c, manual)
        )
        self._email_thread.error.connect(
            lambda msg: self._on_email_error(msg, manual)
        )
        self._email_thread.start()

    def _on_email_error(self, msg: str, manual: bool):
        self._email_btn.setEnabled(True)
        self._update_email_button()
        self._count_lbl.setText("Email check failed.")
        if manual:
            QMessageBox.warning(self, "Email", f"Could not check email:\n\n{msg}")

    def _on_email_fetched(self, scanned: int, saved: list, cfg, manual: bool):
        self._email_btn.setEnabled(True)
        # Persist the advanced UID cursor so we never re-pull the same mail.
        try:
            ef.save_config(self._inbox.slug, cfg)
        except Exception:
            pass
        added = 0
        for item in saved:
            meta = {"from": item.get("from", ""),
                    "from_name": item.get("from_name", ""),
                    "subject": item.get("subject", ""),
                    "date": item.get("date", "")}
            try:
                if self._inbox.ingest_file(item["path"], source=doc_inbox.SOURCE_EMAIL,
                                           email_meta=meta, move=True):
                    added += 1
            except Exception:
                pass
        self.refresh()
        self._update_email_button()
        if added:
            self._count_lbl.setText(f"📧 {added} new document(s) from email.")
        elif manual:
            self._count_lbl.setText("No new email attachments.")

    # ── Process (single AI pass: classify + extract) ────────────────────────
    def _process(self):
        doc = self._selected_doc()
        if not doc:
            return
        from core.ai_routing import routing, ROUTE_LOCKED
        if routing.resolve("document_inbox") == ROUTE_LOCKED:
            QMessageBox.information(
                self, "Anthropic key needed",
                "The Document Inbox runs on your own Anthropic key. Add it in "
                "Settings → AI / Anthropic Key."
            )
            return
        try:
            ledger_names = [l["name"] for l in self._tree.get_all_ledgers()]
        except Exception:
            ledger_names = []

        self._detail_status.setText("Reading the document…")
        self._process_btn.setEnabled(False)
        self._drafts_tbl.setRowCount(0)
        self._drafts = []
        self._post_btn.setEnabled(False)

        self._proc_thread = ProcessThread(
            doc["id"], doc["stored_path"], ledger_names, self._company_name
        )
        self._proc_thread.done.connect(self._on_processed)
        self._proc_thread.error.connect(self._on_process_error)
        self._proc_thread.start()

    def _on_process_error(self, doc_id: int, msg: str):
        self._process_btn.setEnabled(True)
        self._detail_status.setText(f"⚠ {msg}")
        self._inbox.mark_error(doc_id, msg)
        self.refresh()

    def _on_processed(self, doc_id: int, auto: dict, result):
        self._process_btn.setEnabled(True)
        doc_type = auto.get("doc_type", "other")
        summary = auto.get("summary", {})
        vouchers = auto.get("vouchers", []) or []

        # Persist the classification + summary in one shot.
        self._inbox.set_classified(
            doc_id, doc_type, auto.get("confidence", 0.0), summary
        )
        if self._current_id == doc_id:
            idx = self._type_combo.findData(doc_type)
            self._type_combo.setCurrentIndex(max(0, idx))
            self._inbox.get(doc_id) and self._render_ai_summary(self._inbox.get(doc_id))

        # Charge the page cost like the reader does.
        try:
            from ai.credit_manager import CreditManager
            d = self._inbox.get(doc_id)
            CreditManager().deduct(result.local_pages, result.claude_pages,
                                   d["stored_name"] if d else "inbox document")
        except Exception:
            pass

        if doc_type == "bank_statement":
            self._detail_status.setText(
                "Detected a bank statement → import it in Bank Reconciliation "
                "(📂 opens the file). One-click hand-off is coming next."
            )
            return
        if doc_type == "other":
            self._detail_status.setText(
                "Detected 'Other' — nothing to post. Held for manual tagging."
            )
            return
        if not vouchers:
            self._detail_status.setText(
                "No transactions found — view the document or reject it."
            )
            return

        self._drafts = vouchers
        self._fill_drafts(vouchers)
        conf = auto.get("confidence", 0.0)
        self._detail_status.setText(
            f"{DOC_TYPE_LABELS.get(doc_type, doc_type)} ({conf*100:.0f}%) — "
            f"{len(vouchers)} draft(s). Check against the document, then accept."
        )
        self._post_btn.setEnabled(True)

    def _fill_drafts(self, vouchers: list):
        self._drafts_tbl.setRowCount(len(vouchers))
        for r, v in enumerate(vouchers):
            conf = float(v.get("confidence", 0))
            chk = QCheckBox()
            chk.setChecked(conf >= 0.7)
            self._drafts_tbl.setCellWidget(r, 0, chk)
            vtype = v.get("voucher_type", "")
            vals = [
                v.get("date", ""), vtype,
                v.get("dr_ledger", ""), v.get("cr_ledger", ""),
                f"Rs.{float(v.get('amount', 0)):,.2f}", f"{conf*100:.0f}%",
            ]
            for c, val in enumerate(vals, 1):
                item = QTableWidgetItem(str(val))
                if c == 2:
                    item.setForeground(QColor(
                        VOUCHER_COLOURS.get(vtype, THEME["text_secondary"])))
                if c == 6:
                    item.setForeground(QColor(
                        THEME["success"] if conf >= 0.9 else
                        THEME["warning"] if conf >= 0.7 else THEME["danger"]))
                self._drafts_tbl.setItem(r, c, item)

    # ── Post ────────────────────────────────────────────────────────────────
    def _post(self):
        from core.voucher_engine import (
            VoucherEngine, VoucherDraft, VoucherLine, VoucherValidationError
        )
        ledger_map = {l["name"]: l["id"] for l in self._tree.get_all_ledgers()}
        engine = VoucherEngine(self._engine.db, self._engine.company_id)
        posted, skipped, errors, first_vid = 0, 0, [], None

        for r in range(self._drafts_tbl.rowCount()):
            chk = self._drafts_tbl.cellWidget(r, 0)
            if not chk or not chk.isChecked():
                continue
            v = self._drafts[r]
            vtype = v.get("voucher_type", "JOURNAL")
            dr_name = v.get("dr_ledger", "").replace(" (NEW)", "").strip()
            cr_name = v.get("cr_ledger", "").replace(" (NEW)", "").strip()
            dr_id, cr_id = ledger_map.get(dr_name), ledger_map.get(cr_name)
            if not dr_id or not cr_id:
                errors.append(f"Row {r+1}: ledger not found — '{dr_name}' / '{cr_name}'")
                skipped += 1
                continue
            try:
                amount = float(v.get("amount", 0))
                date, narr, ref = v.get("date", ""), v.get("narration", ""), v.get("reference", "")
                if vtype == "PAYMENT":
                    draft = engine.build_payment(date, dr_id, cr_id, amount, narr, ref)
                elif vtype == "RECEIPT":
                    draft = engine.build_receipt(date, cr_id, dr_id, amount, narr, ref)
                elif vtype == "CONTRA":
                    draft = engine.build_contra(date, cr_id, dr_id, amount, narr)
                else:
                    draft = VoucherDraft(
                        voucher_type="JOURNAL", voucher_date=date,
                        narration=narr, reference=ref,
                        lines=[VoucherLine(ledger_id=dr_id, dr_amount=amount),
                               VoucherLine(ledger_id=cr_id, cr_amount=amount)],
                    )
                draft.source = "AI_DOC"
                vid = engine.post(draft)
                first_vid = first_vid or (vid if isinstance(vid, int) else None)
                posted += 1
            except VoucherValidationError as e:
                errors.append(f"Row {r+1}: {'; '.join(e.errors)}")
                skipped += 1
            except Exception as e:
                errors.append(f"Row {r+1}: {e}")
                skipped += 1

        if posted:
            try:
                from core.license_manager import LicenseManager
                LicenseManager().record_transaction_posted("ai_voucher", count=posted)
            except Exception:
                pass
            if self._current_id:
                self._inbox.mark_posted(self._current_id, voucher_id=first_vid)
                self.refresh()

        msg = f"Posted: {posted}\nSkipped: {skipped}"
        if errors:
            msg += "\n\nIssues:\n" + "\n".join(errors[:10])
        if posted:
            QMessageBox.information(self, "Done", msg)
            self._drafts_tbl.setRowCount(0)
            self._drafts = []
            self._post_btn.setEnabled(False)
            self._detail_status.setText(f"Posted {posted} voucher(s).")
        else:
            QMessageBox.warning(self, "Nothing posted", msg)

    def _reject(self):
        doc = self._selected_doc()
        if not doc:
            return
        self._inbox.mark_rejected(doc["id"])
        self.refresh()
        self._detail_status.setText("Rejected.")
