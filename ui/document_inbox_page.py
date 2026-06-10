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
    QHeaderView, QAbstractItemView, QMessageBox, QPlainTextEdit,
    QLineEdit, QFormLayout, QScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QColor, QDesktopServices

from ui.theme import THEME, VOUCHER_COLOURS
from ui.widgets import make_label
from ui.document_review import DocumentPreview
from core import doc_inbox
from core.doc_inbox import DocInbox
from core import email_fetcher as ef
from ai.doc_classifier import DOC_TYPES as _CLS_TYPES

# Voucher types the AI emits (and that we can post as a simple 2-line entry).
_VOUCHER_TYPES = ["PAYMENT", "RECEIPT", "JOURNAL", "CONTRA"]

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
        self._batch_thread = None
        self._current_id = None
        self._drafts = []                 # drafts for the doc on screen
        self._drafts_by_doc = {}          # doc_id -> [draft dicts] (session memory)
        self._posted_keys = set()         # (doc_id, idx) already posted this session
        self._draft_idx = 0               # which draft is showing in the panel
        self._dr_new = False              # current Dr ledger needs creating
        self._cr_new = False              # current Cr ledger needs creating
        self._batch = []                  # process-all work list
        self._batch_i = 0
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

        # ── Pane 1 — queue ──────────────────────────────────────────────────
        self._queue = QTableWidget()
        self._queue.setColumnCount(4)
        self._queue.setHorizontalHeaderLabels(["Document", "Type", "Status", "Conf"])
        qh = self._queue.horizontalHeader()
        qh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c, w in {1: 110, 2: 84, 3: 50}.items():
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

        # ── Pane 2 — in-app document preview ────────────────────────────────
        self._preview = DocumentPreview()
        split.addWidget(self._preview)

        # ── Pane 3 — actions + editable voucher review ──────────────────────
        detail = QFrame()
        detail.setObjectName("card")
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(16, 14, 16, 14)
        dl.setSpacing(8)

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

        # Type override (classification)
        type_row = QHBoxLayout()
        type_row.addWidget(make_label("Document type"))
        self._type_combo = QComboBox()
        self._type_combo.setFixedHeight(28)
        for key in _CLS_TYPES:
            self._type_combo.addItem(DOC_TYPE_LABELS.get(key, key), key)
        type_row.addWidget(self._type_combo, 1)
        dl.addLayout(type_row)

        # Action buttons
        act_row = QHBoxLayout()
        self._process_btn = QPushButton("⚡  Process with AI")
        self._process_btn.setObjectName("btn_primary")
        self._process_btn.setFixedHeight(30)
        self._process_btn.setToolTip(
            "One AI pass on your own key — reads this document, decides its "
            "type, and drafts the voucher(s) for you to review and approve."
        )
        self._process_btn.clicked.connect(self._process)
        self._process_all_btn = QPushButton("⚡⚡  Process All")
        self._process_all_btn.setFixedHeight(30)
        self._process_all_btn.setToolTip(
            "Read every pending document in the background, so the drafts are "
            "ready and you just review & approve down the queue."
        )
        self._process_all_btn.clicked.connect(self._process_all)
        self._reject_btn = QPushButton("✕  Reject")
        self._reject_btn.setFixedHeight(30)
        self._reject_btn.clicked.connect(self._reject)
        act_row.addWidget(self._process_btn)
        act_row.addWidget(self._process_all_btn)
        act_row.addWidget(self._reject_btn)
        dl.addLayout(act_row)

        self._detail_status = QLabel("")
        self._detail_status.setWordWrap(True)
        self._detail_status.setStyleSheet(
            f"color:{THEME['text_secondary']};font-size:11px;"
        )
        dl.addWidget(self._detail_status)

        # Divider
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setStyleSheet(f"color:{THEME['border']};")
        dl.addWidget(rule)

        # ── Proposed voucher (editable, one at a time) ──────────────────────
        nav = QHBoxLayout()
        vh = QLabel("Proposed voucher")
        vh.setStyleSheet(
            f"font-size:12px;font-weight:bold;color:{THEME['text_primary']};"
        )
        nav.addWidget(vh)
        nav.addStretch()
        self._prev_btn = QPushButton("‹")
        self._prev_btn.setFixedSize(28, 24)
        self._prev_btn.clicked.connect(lambda: self._step_draft(-1))
        self._draft_counter = QLabel("")
        self._draft_counter.setStyleSheet(
            f"color:{THEME['text_secondary']};font-size:11px;"
        )
        self._next_btn = QPushButton("›")
        self._next_btn.setFixedSize(28, 24)
        self._next_btn.clicked.connect(lambda: self._step_draft(1))
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._draft_counter)
        nav.addWidget(self._next_btn)
        dl.addLayout(nav)

        self._voucher_box = QFrame()
        form = QFormLayout(self._voucher_box)
        form.setContentsMargins(0, 4, 0, 4)
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._f_type = QComboBox()
        self._f_type.addItems(_VOUCHER_TYPES)
        self._f_type.setFixedHeight(28)
        form.addRow(make_label("Type"), self._f_type)

        self._f_date = QLineEdit()
        self._f_date.setPlaceholderText("YYYY-MM-DD")
        self._f_date.setFixedHeight(28)
        form.addRow(make_label("Date"), self._f_date)

        self._f_dr = QComboBox()
        self._f_dr.setEditable(True)
        self._f_dr.setFixedHeight(28)
        self._f_dr.currentTextChanged.connect(lambda _: self._refresh_new_flags())
        form.addRow(make_label("Debit (Dr)"), self._f_dr)
        self._f_dr_group = QComboBox()
        self._f_dr_group.setFixedHeight(26)
        self._dr_new_row = make_label("⚠ create Dr under")
        self._dr_new_row.setStyleSheet(f"color:{THEME['warning']};font-size:11px;")
        form.addRow(self._dr_new_row, self._f_dr_group)

        self._f_cr = QComboBox()
        self._f_cr.setEditable(True)
        self._f_cr.setFixedHeight(28)
        self._f_cr.currentTextChanged.connect(lambda _: self._refresh_new_flags())
        form.addRow(make_label("Credit (Cr)"), self._f_cr)
        self._f_cr_group = QComboBox()
        self._f_cr_group.setFixedHeight(26)
        self._cr_new_row = make_label("⚠ create Cr under")
        self._cr_new_row.setStyleSheet(f"color:{THEME['warning']};font-size:11px;")
        form.addRow(self._cr_new_row, self._f_cr_group)

        self._f_amount = QLineEdit()
        self._f_amount.setFixedHeight(28)
        form.addRow(make_label("Amount"), self._f_amount)

        self._f_narration = QLineEdit()
        self._f_narration.setFixedHeight(28)
        form.addRow(make_label("Narration"), self._f_narration)

        self._f_reference = QLineEdit()
        self._f_reference.setFixedHeight(28)
        form.addRow(make_label("Reference"), self._f_reference)

        self._f_conf = QLabel("")
        self._f_conf.setStyleSheet(f"font-size:11px;color:{THEME['text_secondary']};")
        form.addRow(make_label("AI confidence"), self._f_conf)

        dl.addWidget(self._voucher_box)

        dl.addWidget(make_label("Source line the AI read"))
        self._f_source = QPlainTextEdit()
        self._f_source.setReadOnly(True)
        self._f_source.setFixedHeight(54)
        self._f_source.setStyleSheet(
            f"QPlainTextEdit {{ background:{THEME['bg_input']}; "
            f"border:1px solid {THEME['border']}; border-radius:6px; "
            f"color:{THEME['text_secondary']}; font-size:11px; }}"
        )
        dl.addWidget(self._f_source)

        # Approve row
        appr = QHBoxLayout()
        self._approve_btn = QPushButton("✓  Approve & Post")
        self._approve_btn.setObjectName("btn_primary")
        self._approve_btn.setFixedHeight(34)
        self._approve_btn.clicked.connect(self._approve_current)
        self._skip_btn = QPushButton("Skip ▸")
        self._skip_btn.setFixedHeight(34)
        self._skip_btn.clicked.connect(lambda: self._step_draft(1))
        appr.addWidget(self._approve_btn, 1)
        appr.addWidget(self._skip_btn)
        dl.addLayout(appr)

        dl.addStretch()

        # Wrap the detail pane in a scroll area so the voucher form is never
        # clipped on shorter windows — it scrolls instead of squeezing.
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_scroll.setWidget(detail)
        detail_scroll.setMinimumWidth(360)
        split.addWidget(detail_scroll)

        split.setSizes([200, 430, 560])      # voucher pane gets the most room
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 1)
        layout.addWidget(split, 1)

        self._set_detail_enabled(False)
        self._show_voucher_panel(False)

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
        self._drafts = []
        self._draft_idx = 0
        if not doc:
            self._set_detail_enabled(False)
            self._show_voucher_panel(False)
            self._preview.clear()
            self._name_lbl.setText("Select a document")
            self._ai_lbl.setText("")
            return
        self._current_id = doc["id"]
        self._set_detail_enabled(
            doc["status"] in ("PENDING", "CLASSIFIED", "APPROVED", "ERROR")
        )
        self._name_lbl.setText(doc["stored_name"])

        # In-app preview — render the document right here, no external window.
        self._preview.show_file(doc["stored_path"])

        dt = doc.get("doc_type") or "other"
        idx = self._type_combo.findData(dt)
        self._type_combo.setCurrentIndex(max(0, idx))

        self._render_ai_summary(doc)

        # If we already extracted drafts for this doc this session, show them
        # so the reviewer can pick up where they left off without re-spending.
        self._drafts = list(self._drafts_by_doc.get(doc["id"], []))
        if self._drafts:
            self._show_voucher_panel(True)
            self._show_draft(0)
        else:
            self._show_voucher_panel(False)

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
                "It's shown on the left. Click “Process with AI” to draft the "
                "voucher(s) for review."
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
                             else "Processed — review and approve each voucher.")

    def _set_detail_enabled(self, on: bool):
        for w in (self._type_combo, self._process_btn, self._process_all_btn,
                  self._reject_btn):
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

    # ── AI readiness / helpers ──────────────────────────────────────────────
    def _ai_ready(self) -> bool:
        from core.ai_routing import routing, ROUTE_LOCKED
        if routing.resolve("document_inbox") == ROUTE_LOCKED:
            QMessageBox.information(
                self, "Anthropic key needed",
                "The Document Inbox runs on your own Anthropic key. Add it in "
                "Settings → AI / Anthropic Key."
            )
            return False
        return True

    def _ledger_names(self) -> list:
        try:
            return [l["name"] for l in self._tree.get_all_ledgers()]
        except Exception:
            return []

    def _group_names(self) -> list:
        try:
            rows = self._engine.db.execute(
                "SELECT name FROM account_groups WHERE company_id=? ORDER BY name",
                (self._engine.company_id,),
            ).fetchall()
            return [r["name"] for r in rows]
        except Exception:
            return ["Sundry Creditors", "Sundry Debtors", "Indirect Expenses"]

    def _charge(self, doc_id: int, result):
        try:
            from ai.credit_manager import CreditManager
            d = self._inbox.get(doc_id)
            CreditManager().deduct(result.local_pages, result.claude_pages,
                                   d["stored_name"] if d else "inbox document")
        except Exception:
            pass

    # ── Process one document (AI pass: classify + extract) ──────────────────
    def _process(self):
        doc = self._selected_doc()
        if not doc or not self._ai_ready():
            return
        self._detail_status.setText("Reading the document…")
        self._process_btn.setEnabled(False)
        self._show_voucher_panel(False)
        self._drafts = []

        self._proc_thread = ProcessThread(
            doc["id"], doc["stored_path"], self._ledger_names(), self._company_name
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
        vouchers = auto.get("vouchers", []) or []

        self._inbox.set_classified(
            doc_id, doc_type, auto.get("confidence", 0.0), auto.get("summary", {})
        )
        self._charge(doc_id, result)
        self._drafts_by_doc[doc_id] = vouchers

        if self._current_id == doc_id:
            d = self._inbox.get(doc_id)
            if d:
                idx = self._type_combo.findData(doc_type)
                self._type_combo.setCurrentIndex(max(0, idx))
                self._render_ai_summary(d)
            self._present_drafts(doc_type, vouchers, auto.get("confidence", 0.0))
        self.refresh()

    def _present_drafts(self, doc_type: str, vouchers: list, conf: float):
        if doc_type == "bank_statement":
            self._detail_status.setText(
                "Detected a bank statement → import it in Bank Reconciliation. "
                "Not posted from here."
            )
            self._show_voucher_panel(False)
            return
        if doc_type == "other":
            self._detail_status.setText(
                "Detected 'Other' — nothing to post. Held for manual tagging."
            )
            self._show_voucher_panel(False)
            return
        if not vouchers:
            self._detail_status.setText(
                "No transactions found — check the document on the left, or reject it."
            )
            self._show_voucher_panel(False)
            return
        self._drafts = list(vouchers)
        self._detail_status.setText(
            f"{DOC_TYPE_LABELS.get(doc_type, doc_type)} ({conf*100:.0f}%) — "
            f"{len(vouchers)} voucher(s). Review & approve each one."
        )
        self._show_voucher_panel(True)
        self._show_draft(0)

    # ── Voucher review panel ────────────────────────────────────────────────
    def _show_voucher_panel(self, on: bool):
        for w in (self._voucher_box, self._f_source, self._approve_btn,
                  self._skip_btn, self._prev_btn, self._next_btn,
                  self._draft_counter):
            w.setVisible(on)

    def _populate_ledger_combos(self):
        names = sorted(self._ledger_names())
        self._ledger_set = set(names)
        for combo in (self._f_dr, self._f_cr):
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            combo.setCurrentText(cur)
            combo.blockSignals(False)
        groups = self._group_names()
        for gc in (self._f_dr_group, self._f_cr_group):
            cur = gc.currentText()
            gc.clear()
            gc.addItems(groups)
            if cur:
                gc.setCurrentText(cur)

    def _show_draft(self, idx: int):
        if not self._drafts:
            self._show_voucher_panel(False)
            return
        idx = max(0, min(idx, len(self._drafts) - 1))
        self._draft_idx = idx
        v = self._drafts[idx]

        self._populate_ledger_combos()

        self._draft_counter.setText(f"{idx + 1} / {len(self._drafts)}")
        self._prev_btn.setEnabled(idx > 0)
        self._next_btn.setEnabled(idx < len(self._drafts) - 1)

        vtype = v.get("voucher_type", "JOURNAL")
        if vtype not in _VOUCHER_TYPES:
            vtype = "JOURNAL"
        self._f_type.setCurrentText(vtype)
        self._f_date.setText(str(v.get("date", "") or ""))
        self._f_dr.setCurrentText((v.get("dr_ledger", "") or "").replace(" (NEW)", "").strip())
        self._f_cr.setCurrentText((v.get("cr_ledger", "") or "").replace(" (NEW)", "").strip())
        try:
            self._f_amount.setText(f"{float(v.get('amount', 0) or 0):.2f}")
        except (TypeError, ValueError):
            self._f_amount.setText("0.00")
        self._f_narration.setText(v.get("narration", "") or "")
        self._f_reference.setText(v.get("reference", "") or "")

        conf = float(v.get("confidence", 0) or 0)
        self._f_conf.setText(f"{conf*100:.0f}%")
        self._f_conf.setStyleSheet(
            "font-size:11px;color:" + (
                THEME["success"] if conf >= 0.9 else
                THEME["warning"] if conf >= 0.7 else THEME["danger"]
            ) + ";"
        )
        self._f_source.setPlainText(v.get("raw_line", "") or v.get("narration", "") or "")

        posted = (self._current_id, idx) in self._posted_keys
        self._approve_btn.setEnabled(not posted)
        self._approve_btn.setText("✓ Posted" if posted else "✓  Approve & Post")

        self._refresh_new_flags()
        # Pre-guess a group for any ledger that will be created.
        if self._dr_new:
            self._guess_group(self._f_dr_group, "Indirect Expenses")
        if self._cr_new:
            self._guess_group(self._f_cr_group, "Sundry Creditors")

    def _guess_group(self, combo, name: str):
        i = combo.findText(name)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _step_draft(self, delta: int):
        if self._drafts:
            self._show_draft(self._draft_idx + delta)

    def _refresh_new_flags(self):
        s = getattr(self, "_ledger_set", set())
        dr = self._f_dr.currentText().strip()
        cr = self._f_cr.currentText().strip()
        self._dr_new = bool(dr) and dr not in s
        self._cr_new = bool(cr) and cr not in s
        self._dr_new_row.setVisible(self._dr_new)
        self._f_dr_group.setVisible(self._dr_new)
        self._cr_new_row.setVisible(self._cr_new)
        self._f_cr_group.setVisible(self._cr_new)

    def _ensure_ledger(self, name: str, group: str | None) -> int:
        name = name.replace(" (NEW)", "").strip()
        existing = {l["name"]: l["id"] for l in self._tree.get_all_ledgers()}
        if name in existing:
            return existing[name]
        grp = (group or "").strip()
        if grp not in set(self._group_names()):
            grp = "Sundry Creditors"
        return self._tree.add_ledger(name, grp)

    # ── Approve & post the voucher on screen ────────────────────────────────
    def _approve_current(self):
        if not self._drafts:
            return
        idx = self._draft_idx
        if (self._current_id, idx) in self._posted_keys:
            self._step_to_next_unposted()
            return

        vtype = self._f_type.currentText().strip() or "JOURNAL"
        date = self._f_date.text().strip()
        dr_name = self._f_dr.currentText().strip()
        cr_name = self._f_cr.currentText().strip()
        narr = self._f_narration.text().strip()
        ref = self._f_reference.text().strip()
        try:
            amount = float(self._f_amount.text().replace(",", "").strip() or 0)
        except ValueError:
            QMessageBox.warning(self, "Check amount", "Amount must be a number.")
            return
        if not date or not dr_name or not cr_name or amount <= 0:
            QMessageBox.warning(
                self, "Incomplete",
                "Date, both ledgers and a positive amount are needed before posting."
            )
            return

        # Slow operation ahead (ledger create + post). Show it's working so a
        # lagging post never looks like nothing happened.
        self._set_posting_state(True)

        try:
            dr_id = self._ensure_ledger(
                dr_name, self._f_dr_group.currentText() if self._dr_new else None)
            cr_id = self._ensure_ledger(
                cr_name, self._f_cr_group.currentText() if self._cr_new else None)
        except Exception as e:
            self._set_posting_state(False)
            QMessageBox.warning(self, "Ledger problem", str(e))
            return

        from core.voucher_engine import (
            VoucherEngine, VoucherDraft, VoucherLine, VoucherValidationError
        )
        engine = VoucherEngine(self._engine.db, self._engine.company_id)
        try:
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
        except VoucherValidationError as e:
            self._set_posting_state(False)
            QMessageBox.warning(self, "Could not post", "; ".join(e.errors))
            return
        except Exception as e:
            self._set_posting_state(False)
            QMessageBox.warning(self, "Could not post", str(e))
            return

        try:
            from core.license_manager import LicenseManager
            LicenseManager().record_transaction_posted("ai_voucher", count=1)
        except Exception:
            pass

        self._posted_keys.add((self._current_id, idx))

        # Mark the document done once every draft on it is posted (updates the
        # queue on the left).
        if all((self._current_id, i) in self._posted_keys
               for i in range(len(self._drafts))):
            self._inbox.mark_posted(
                self._current_id, voucher_id=vid if isinstance(vid, int) else None)
            self.refresh()

        # Unmistakable "done": blank the voucher and lock the button to
        # "✓ Posted". We deliberately do NOT auto-jump to the next document —
        # with a slow post the silent jump made it impossible to tell anything
        # happened. Move on via Skip ▸ or by picking the next item in the queue.
        self._blank_detail()
        self._approve_btn.setEnabled(False)
        self._approve_btn.setText("✓ Posted")
        self._detail_status.setText(
            f"✓ Posted voucher {idx + 1} of {len(self._drafts)}  —  pick the next document."
        )
        self._detail_status.setStyleSheet(
            f"color:{THEME['success']}; font-weight:bold;")

    def _set_posting_state(self, on: bool) -> None:
        """Toggle the Approve button between its normal state and a disabled
        'Posting…' state, repainting immediately so a slow post shows progress."""
        self._approve_btn.setEnabled(not on)
        self._approve_btn.setText("Posting…" if on else "✓  Approve & Post")
        if on:
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

    def _blank_detail(self) -> None:
        """Clear the editable voucher fields so a just-posted entry visibly
        empties out. Guarded — a missing field never breaks the post."""
        for w in (getattr(self, "_f_date", None), getattr(self, "_f_amount", None),
                  getattr(self, "_f_narration", None), getattr(self, "_f_reference", None)):
            try:
                w.clear()
            except Exception:
                pass
        for c in (getattr(self, "_f_dr", None), getattr(self, "_f_cr", None)):
            try:
                c.setEditText("")
            except Exception:
                pass
        try:
            self._f_source.clear()
        except Exception:
            pass
        try:
            self._f_conf.setText("")
        except Exception:
            pass

    def _step_to_next_unposted(self):
        n = len(self._drafts)
        for off in range(1, n + 1):
            j = (self._draft_idx + off) % n
            if (self._current_id, j) not in self._posted_keys:
                self._show_draft(j)
                return
        self._show_draft(self._draft_idx)   # refresh "Posted" state

    def _advance_to_next_doc(self):
        sel = self._queue.selectionModel().selectedRows()
        cur_row = sel[0].row() if sel else -1
        n = self._queue.rowCount()
        for off in range(1, n + 1):
            r = (cur_row + off) % n
            item = self._queue.item(r, 0)
            if not item:
                continue
            d = self._inbox.get(item.data(Qt.ItemDataRole.UserRole))
            if d and d["status"] in ("PENDING", "CLASSIFIED", "APPROVED", "ERROR"):
                if r != cur_row:
                    self._queue.selectRow(r)
                return
        self._detail_status.setText("All caught up — no more documents to review. ✓")

    # ── Process every pending document in the background ────────────────────
    def _process_all(self):
        if not self._ai_ready():
            return
        pending = [d for d in self._inbox.list()
                   if d["status"] in ("PENDING", "ERROR")]
        if not pending:
            self._detail_status.setText("Nothing pending to process.")
            return
        self._batch = pending
        self._batch_i = 0
        self._process_all_btn.setEnabled(False)
        self._process_btn.setEnabled(False)
        self._run_batch_next()

    def _run_batch_next(self):
        if self._batch_i >= len(self._batch):
            self._process_all_btn.setEnabled(True)
            self._process_btn.setEnabled(True)
            self._detail_status.setText(
                f"Processed {len(self._batch)} document(s). "
                f"Review & approve down the queue."
            )
            self.refresh()
            self._advance_to_next_doc_from_top()
            return
        d = self._batch[self._batch_i]
        self._count_lbl.setText(
            f"Processing {self._batch_i + 1} of {len(self._batch)}…"
        )
        self._batch_thread = ProcessThread(
            d["id"], d["stored_path"], self._ledger_names(), self._company_name
        )
        self._batch_thread.done.connect(self._on_batch_done)
        self._batch_thread.error.connect(self._on_batch_error)
        self._batch_thread.start()

    def _on_batch_done(self, doc_id: int, auto: dict, result):
        self._inbox.set_classified(
            doc_id, auto.get("doc_type", "other"),
            auto.get("confidence", 0.0), auto.get("summary", {})
        )
        self._charge(doc_id, result)
        self._drafts_by_doc[doc_id] = auto.get("vouchers", []) or []
        self._batch_i += 1
        self._run_batch_next()

    def _on_batch_error(self, doc_id: int, msg: str):
        self._inbox.mark_error(doc_id, msg)
        self._batch_i += 1
        self._run_batch_next()

    def _advance_to_next_doc_from_top(self):
        for r in range(self._queue.rowCount()):
            item = self._queue.item(r, 0)
            if not item:
                continue
            d = self._inbox.get(item.data(Qt.ItemDataRole.UserRole))
            if d and d["status"] in ("CLASSIFIED", "APPROVED", "PENDING", "ERROR"):
                self._queue.selectRow(r)
                return

    def _reject(self):
        doc = self._selected_doc()
        if not doc:
            return
        self._inbox.mark_rejected(doc["id"])
        self.refresh()
        self._detail_status.setText("Rejected.")
        self._advance_to_next_doc()
