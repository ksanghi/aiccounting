"""
Reports pages — UI for all reports with Excel and PDF export.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QDateEdit, QFrame,
    QHeaderView, QAbstractItemView, QMessageBox, QFileDialog,
    QScrollArea, QSplitter, QSizePolicy, QComboBox,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui  import QColor

from ui.theme   import THEME, VOUCHER_COLOURS
from ui.widgets import make_label, SmartDateEdit


# ── helpers ───────────────────────────────────────────────────────────────────

def _fy_start() -> QDate:
    today = QDate.currentDate()
    y = today.year() if today.month() >= 4 else today.year() - 1
    return QDate(y, 4, 1)

def _fmt(v: float) -> str:
    return f"₹{v:,.2f}"

def _item(text: str, right: bool = False, colour: str = None,
          bold: bool = False) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    it.setTextAlignment(
        Qt.AlignmentFlag.AlignVCenter |
        (Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft)
    )
    if colour:
        it.setForeground(QColor(colour))
    if bold:
        from PySide6.QtGui import QFont
        f = QFont()
        f.setBold(True)
        it.setFont(f)
    return it

def _make_table(headers: list, stretch_cols: list = None) -> QTableWidget:
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.verticalHeader().setVisible(False)
    t.setShowGrid(False)
    hdr = t.horizontalHeader()
    for c in range(len(headers)):
        if stretch_cols and c in stretch_cols:
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        else:
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
    return t


# ── base class ────────────────────────────────────────────────────────────────

class _ReportBase(QWidget):
    TITLE    = "Report"
    SUBTITLE = ""
    AS_OF    = False   # True → single date; False → from/to range

    def __init__(self, rpt, parent=None):
        super().__init__(parent)
        self.rpt   = rpt
        self._data = None
        self._build_shell()

    # ── shell layout ──────────────────────────────────────────────────────────

    def _build_shell(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 0, 24, 24)
        root.setSpacing(8)

        lbl = QLabel(self.TITLE)
        lbl.setObjectName("page_title")
        root.addWidget(lbl)
        if self.SUBTITLE:
            sub = QLabel(self.SUBTITLE)
            sub.setObjectName("page_subtitle")
            root.addWidget(sub)

        # filter bar
        fbar = QFrame()
        fbar.setObjectName("card")
        frow = QHBoxLayout(fbar)
        frow.setContentsMargins(12, 10, 12, 10)
        frow.setSpacing(10)

        if self.AS_OF:
            frow.addWidget(make_label("As of"))
            self.as_of = SmartDateEdit(QDate.currentDate())
            self.as_of.setDisplayFormat("dd-MMM-yyyy")
            self.as_of.setFixedHeight(30)
            frow.addWidget(self.as_of)
        else:
            frow.addWidget(make_label("From"))
            self.from_date = SmartDateEdit(_fy_start())
            self.from_date.setDisplayFormat("dd-MMM-yyyy")
            self.from_date.setFixedHeight(30)
            frow.addWidget(self.from_date)

            frow.addWidget(make_label("To"))
            self.to_date = SmartDateEdit(QDate.currentDate())
            self.to_date.setDisplayFormat("dd-MMM-yyyy")
            self.to_date.setFixedHeight(30)
            frow.addWidget(self.to_date)

        self._extra_filters(frow)
        frow.addStretch()

        ref_btn = QPushButton("↻  Refresh")
        ref_btn.setFixedHeight(30)
        ref_btn.clicked.connect(self.refresh)
        frow.addWidget(ref_btn)

        xl_btn = QPushButton("⬇  Excel")
        xl_btn.setFixedHeight(30)
        xl_btn.setFixedWidth(88)
        xl_btn.clicked.connect(self._save_excel)
        frow.addWidget(xl_btn)

        pdf_btn = QPushButton("⬇  PDF")
        pdf_btn.setFixedHeight(30)
        pdf_btn.setFixedWidth(76)
        pdf_btn.clicked.connect(self._save_pdf)
        frow.addWidget(pdf_btn)

        print_btn = QPushButton("🖶  Print")
        print_btn.setFixedHeight(30)
        print_btn.setFixedWidth(80)
        print_btn.setToolTip("Print preview — opens a Print dialog (Ctrl+P)")
        print_btn.clicked.connect(self._print)
        frow.addWidget(print_btn)

        root.addWidget(fbar)

        self._body = QVBoxLayout()
        self._body.setSpacing(6)
        root.addLayout(self._body, 1)

        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;"
        )
        root.addWidget(self._status)

    def _extra_filters(self, row):
        pass

    def _dates(self):
        if self.AS_OF:
            return self.as_of.date().toString("yyyy-MM-dd")
        return (self.from_date.date().toString("yyyy-MM-dd"),
                self.to_date.date().toString("yyyy-MM-dd"))

    def refresh(self):
        raise NotImplementedError

    # ── export ────────────────────────────────────────────────────────────────

    def _default_export_name(self, ext: str) -> str:
        """Suggested filename:  <Company>_<Report>_<Date>.<ext>"""
        import re, os
        from pathlib import Path

        co = (self.rpt.get_company().get("name") or "AccGenie").strip()
        # Sanitise for cross-platform filename use: drop punctuation,
        # collapse whitespace to a single underscore.
        co = re.sub(r"[^\w\s-]", "", co)
        co = re.sub(r"\s+", "_", co).strip("_") or "AccGenie"

        title = self.TITLE.replace(" & ", "_").replace(" ", "_")

        d = self._dates()
        date_part = d if isinstance(d, str) else f"{d[0]}_to_{d[1]}"

        downloads = Path.home() / "Downloads"
        folder = downloads if downloads.exists() else Path.home()
        return str(folder / f"{co}_{title}_{date_part}.{ext}")

    def _save_excel(self):
        from core.exporters import ExcelExporter
        exp = ExcelExporter()
        if not exp.available:
            QMessageBox.warning(self, "Excel Export",
                "openpyxl is not installed.\nRun:  pip install openpyxl")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save as Excel", self._default_export_name("xlsx"),
            "Excel (*.xlsx)")
        if path:
            try:
                self._do_excel(exp, path)
                QMessageBox.information(self, "Saved", path)
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    def _save_pdf(self):
        from core.exporters import PDFExporter
        exp = PDFExporter()
        if not exp.available:
            QMessageBox.warning(self, "PDF Export",
                "reportlab is not installed.\nRun:  pip install reportlab")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save as PDF", self._default_export_name("pdf"),
            "PDF (*.pdf)")
        if path:
            try:
                self._do_pdf(exp, path)
                QMessageBox.information(self, "Saved", path)
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

    # ── print preview ─────────────────────────────────────────────────────────

    def _print(self):
        from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
        from PySide6.QtGui  import QTextDocument, QPageSize
        from PySide6.QtCore import QMarginsF

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageMargins(QMarginsF(12, 12, 12, 12))

        doc = QTextDocument()
        doc.setHtml(self._build_print_html())

        dlg = QPrintPreviewDialog(printer, self)
        dlg.setWindowTitle(f"Print — {self.TITLE}")
        dlg.resize(900, 700)
        dlg.paintRequested.connect(doc.print_)
        dlg.exec()

    def _build_print_html(self) -> str:
        """Stitch all visible QTableWidgets on the page into a print-ready
        HTML document. Subclasses can override for custom layouts (e.g. the
        side-by-side Balance Sheet)."""
        co = self.rpt.get_company().get("name", "")
        d = self._dates()
        period = d if isinstance(d, str) else f"{d[0]} to {d[1]}"

        parts = [
            "<div style='font-family:sans-serif'>",
            f"<h2 style='margin:0'>{co}</h2>" if co else "",
            f"<h3 style='margin:4px 0;color:#444'>{self.TITLE}</h3>",
            f"<p style='color:#666;margin:0 0 12px 0'>{period}</p>",
        ]
        for tbl in self.findChildren(QTableWidget):
            parts.append(self._table_to_html(tbl))
        parts.append("</div>")
        return "".join(parts)

    def _table_to_html(self, table: QTableWidget) -> str:
        rows = [
            "<table border=1 cellspacing=0 cellpadding=4 "
            "style='border-collapse:collapse;width:100%;"
            "margin-bottom:12px;font-size:10pt'>"
        ]
        headers = []
        for c in range(table.columnCount()):
            h = table.horizontalHeaderItem(c)
            headers.append(h.text() if h else "")
        rows.append(
            "<thead><tr>" + "".join(
                f"<th style='background:#eee;text-align:left;padding:4px'>"
                f"{h}</th>" for h in headers
            ) + "</tr></thead><tbody>"
        )
        for r in range(table.rowCount()):
            cells = []
            for c in range(table.columnCount()):
                it = table.item(r, c)
                txt = it.text() if it else ""
                # Right-align money columns (heuristic: 3rd column onward).
                align = "right" if c >= 2 else "left"
                cells.append(
                    f"<td style='text-align:{align};padding:3px 4px'>"
                    f"{txt}</td>"
                )
            rows.append("<tr>" + "".join(cells) + "</tr>")
        rows.append("</tbody></table>")
        return "".join(rows)

    def _do_excel(self, exp, path): pass
    def _do_pdf(self, exp, path):   pass


# ── 1. Trial Balance ──────────────────────────────────────────────────────────

class TrialBalancePage(_ReportBase):
    TITLE    = "Trial Balance"
    SUBTITLE = "Ledger-wise debit and credit summary for the period"
    AS_OF    = True

    def _build_shell(self):
        super()._build_shell()
        self._table = _make_table(
            ["#","Ledger","Group","Nature",
             "Op Dr","Op Cr","Txn Dr","Txn Cr","Cl Dr","Cl Cr"],
            stretch_cols=[1]
        )
        self._body.addWidget(self._table, 1)

    def refresh(self):
        as_of = self._dates()
        self._data = self.rpt.trial_balance(as_of)
        t = self._table
        t.setRowCount(len(self._data))
        for i, d in enumerate(self._data):
            net_dr = d["closing_dr"]
            net_cr = d["closing_cr"]
            colour = THEME["accent"] if net_dr else THEME["warning"]
            t.setItem(i, 0, _item(str(i+1), right=True))
            t.setItem(i, 1, _item(d["ledger"]))
            t.setItem(i, 2, _item(d["group"]))
            t.setItem(i, 3, _item(d["nature"]))
            t.setItem(i, 4, _item(_fmt(d["opening_dr"]), right=True))
            t.setItem(i, 5, _item(_fmt(d["opening_cr"]), right=True))
            t.setItem(i, 6, _item(_fmt(d["txn_dr"]),     right=True))
            t.setItem(i, 7, _item(_fmt(d["txn_cr"]),     right=True))
            t.setItem(i, 8, _item(_fmt(d["closing_dr"]), right=True, colour=colour if net_dr else None))
            t.setItem(i, 9, _item(_fmt(d["closing_cr"]), right=True, colour=colour if net_cr else None))

        tot_dr = sum(d["closing_dr"] for d in self._data)
        tot_cr = sum(d["closing_cr"] for d in self._data)
        diff   = round(tot_dr - tot_cr, 2)
        bal    = "✓ Balanced" if abs(diff) < 0.01 else f"⚠ Diff {_fmt(diff)}"
        col    = THEME["success"] if abs(diff) < 0.01 else THEME["danger"]
        self._status.setText(
            f"{len(self._data)} ledgers  |  "
            f"Total Dr {_fmt(tot_dr)}  |  Total Cr {_fmt(tot_cr)}  |  "
            f"<span style='color:{col};font-weight:bold'>{bal}</span>"
        )
        self._status.setTextFormat(Qt.TextFormat.RichText)

    def _do_excel(self, exp, path):
        exp.trial_balance(self._data, self.rpt.get_company(), self._dates(), path)

    def _do_pdf(self, exp, path):
        exp.trial_balance(self._data, self.rpt.get_company(), self._dates(), path)


# ── 2. Profit & Loss ──────────────────────────────────────────────────────────

class ProfitLossPage(_ReportBase):
    TITLE    = "Profit & Loss"
    SUBTITLE = "Income and expenses for the selected period"

    def _build_shell(self):
        super()._build_shell()

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Income side
        inc_frame = QFrame()
        inc_frame.setObjectName("card")
        inc_layout = QVBoxLayout(inc_frame)
        inc_layout.setContentsMargins(14, 12, 14, 12)
        inc_layout.setSpacing(4)
        inc_hdr = QLabel("INCOME")
        inc_hdr.setStyleSheet(
            f"color:{THEME['success']}; font-weight:bold; font-size:12px;"
        )
        inc_layout.addWidget(inc_hdr)
        self._inc_table = _make_table(["Ledger","Group","Amount"], stretch_cols=[0])
        inc_layout.addWidget(self._inc_table, 1)
        self._inc_total = QLabel("")
        self._inc_total.setStyleSheet(
            f"color:{THEME['success']}; font-weight:bold; font-size:13px; padding:6px 0;"
        )
        inc_layout.addWidget(self._inc_total)
        splitter.addWidget(inc_frame)

        # Expense side
        exp_frame = QFrame()
        exp_frame.setObjectName("card")
        exp_layout = QVBoxLayout(exp_frame)
        exp_layout.setContentsMargins(14, 12, 14, 12)
        exp_layout.setSpacing(4)
        exp_hdr = QLabel("EXPENSES")
        exp_hdr.setStyleSheet(
            f"color:{THEME['danger']}; font-weight:bold; font-size:12px;"
        )
        exp_layout.addWidget(exp_hdr)
        self._exp_table = _make_table(["Ledger","Group","Amount"], stretch_cols=[0])
        exp_layout.addWidget(self._exp_table, 1)
        self._exp_total = QLabel("")
        self._exp_total.setStyleSheet(
            f"color:{THEME['danger']}; font-weight:bold; font-size:13px; padding:6px 0;"
        )
        exp_layout.addWidget(self._exp_total)
        splitter.addWidget(exp_frame)

        self._body.addWidget(splitter, 1)

        # Net profit bar
        net_bar = QFrame()
        net_bar.setObjectName("card")
        net_row = QHBoxLayout(net_bar)
        net_row.setContentsMargins(18, 10, 18, 10)
        net_lbl = QLabel("Net Profit / (Loss)")
        net_lbl.setStyleSheet("font-size:13px; font-weight:bold;")
        self._net_lbl = QLabel("")
        self._net_lbl.setStyleSheet("font-size:16px; font-weight:bold;")
        net_row.addWidget(net_lbl)
        net_row.addStretch()
        net_row.addWidget(self._net_lbl)
        self._body.addWidget(net_bar)

    def _fill_table(self, table, rows, amount_col=2):
        table.setRowCount(len(rows))
        for i, d in enumerate(rows):
            table.setItem(i, 0, _item(d["ledger"]))
            table.setItem(i, 1, _item(d["group"]))
            table.setItem(i, 2, _item(_fmt(d["amount"]), right=True))

    def refresh(self):
        fd, td = self._dates()
        self._data = self.rpt.profit_and_loss(fd, td)
        self._fill_table(self._inc_table, self._data["income"])
        self._fill_table(self._exp_table, self._data["expenses"])
        self._inc_total.setText(f"Total Income: {_fmt(self._data['total_income'])}")
        self._exp_total.setText(f"Total Expenses: {_fmt(self._data['total_expense'])}")
        np = self._data["net_profit"]
        colour = THEME["success"] if np >= 0 else THEME["danger"]
        label  = "Profit" if np >= 0 else "Loss"
        self._net_lbl.setText(_fmt(abs(np)))
        self._net_lbl.setStyleSheet(
            f"font-size:16px; font-weight:bold; color:{colour};"
        )
        self._status.setText(
            f"Period: {fd}  →  {td}  |  "
            f"Income: {_fmt(self._data['total_income'])}  |  "
            f"Expenses: {_fmt(self._data['total_expense'])}  |  "
            f"Net {label}: {_fmt(np)}"
        )

    def _do_excel(self, exp, path):
        exp.profit_and_loss(self._data, self.rpt.get_company(), path)

    def _do_pdf(self, exp, path):
        exp.profit_and_loss(self._data, self.rpt.get_company(), path)


# ── 3. Balance Sheet ──────────────────────────────────────────────────────────

class BalanceSheetPage(_ReportBase):
    TITLE    = "Balance Sheet"
    SUBTITLE = "Assets and liabilities as of a date"
    AS_OF    = True

    def _build_shell(self):
        super()._build_shell()
        splitter = QSplitter(Qt.Orientation.Horizontal)

        for side in ("assets", "liabilities"):
            frame = QFrame()
            frame.setObjectName("card")
            lay = QVBoxLayout(frame)
            lay.setContentsMargins(14, 12, 14, 12)
            lay.setSpacing(4)
            hdr_text = "ASSETS" if side == "assets" else "LIABILITIES & CAPITAL"
            hdr_col  = THEME["accent"] if side == "assets" else THEME["warning"]
            hdr = QLabel(hdr_text)
            hdr.setStyleSheet(f"color:{hdr_col}; font-weight:bold; font-size:12px;")
            lay.addWidget(hdr)
            tbl = _make_table(["Ledger","Group","Balance","Side"], stretch_cols=[0])
            lay.addWidget(tbl, 1)
            total_lbl = QLabel("")
            total_lbl.setStyleSheet(
                f"color:{hdr_col}; font-weight:bold; font-size:13px; padding:6px 0;"
            )
            lay.addWidget(total_lbl)
            splitter.addWidget(frame)
            if side == "assets":
                self._ast_table = tbl
                self._ast_total = total_lbl
            else:
                self._lib_table = tbl
                self._lib_total = total_lbl

        self._body.addWidget(splitter, 1)

    def _extra_filters(self, row):
        row.addWidget(make_label("Format"))
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItem("Grouped", "grouped")
        self._fmt_combo.addItem("Flat",    "flat")
        self._fmt_combo.addItem("Schedule III (coming soon)", "schedule3")
        self._fmt_combo.model().item(2).setEnabled(False)
        self._fmt_combo.setFixedHeight(30)
        self._fmt_combo.currentIndexChanged.connect(self._on_fmt_change)
        row.addWidget(self._fmt_combo)

    def _on_fmt_change(self):
        if getattr(self, "_data", None):
            # Re-render with the new format. Don't re-hit the DB.
            self._fill(self._ast_table, self._data["assets"],
                       THEME["accent"],  natural_side="Dr")
            self._fill(self._lib_table, self._data["liabilities"],
                       THEME["warning"], natural_side="Cr")

    def _fill(self, table, rows, colour, natural_side="Dr"):
        fmt = (self._fmt_combo.currentData()
               if hasattr(self, "_fmt_combo") else "grouped")

        if fmt == "flat":
            table.setRowCount(len(rows))
            for i, d in enumerate(rows):
                table.setItem(i, 0, _item(d["ledger"]))
                table.setItem(i, 1, _item(d["group"]))
                table.setItem(i, 2, _item(_fmt(d["balance"]),
                                          right=True, colour=colour))
                table.setItem(i, 3, _item(d["side"]))
            return

        # Grouped: bucket by chart-of-accounts group, header + ledgers +
        # implicit subtotal in the group header row.
        groups: dict[str, list[dict]] = {}
        for r in rows:
            groups.setdefault(r["group"], []).append(r)

        total_rows = sum(len(ls) + 1 for ls in groups.values())
        table.setRowCount(total_rows)
        bg = QColor(THEME["bg_input"])

        i = 0
        for group_name in sorted(groups.keys()):
            ledgers = groups[group_name]
            signed = sum(
                l["balance"] if l["side"] == natural_side else -l["balance"]
                for l in ledgers
            )
            sub_side = (natural_side if signed >= 0
                        else ("Cr" if natural_side == "Dr" else "Dr"))

            # Group header row — bold + tinted background.
            cells = [
                _item(group_name,             bold=True),
                _item("",                     bold=True),
                _item(_fmt(abs(signed)),      right=True, bold=True,
                      colour=colour),
                _item(sub_side,               bold=True),
            ]
            for c, it in enumerate(cells):
                it.setBackground(bg)
                table.setItem(i, c, it)
            i += 1

            # Indented ledger rows under the header.
            for d in ledgers:
                table.setItem(i, 0, _item(f"    {d['ledger']}"))
                table.setItem(i, 1, _item(""))
                table.setItem(i, 2, _item(_fmt(d["balance"]),
                                          right=True, colour=colour))
                table.setItem(i, 3, _item(d["side"]))
                i += 1

    def refresh(self):
        as_of = self._dates()
        self._data = self.rpt.balance_sheet(as_of)
        self._fill(self._ast_table, self._data["assets"],
                   THEME["accent"],  natural_side="Dr")
        self._fill(self._lib_table, self._data["liabilities"],
                   THEME["warning"], natural_side="Cr")
        self._ast_total.setText(f"Total Assets: {_fmt(self._data['total_assets'])}")
        self._lib_total.setText(f"Total Liabilities: {_fmt(self._data['total_liabilities'])}")
        diff = round(self._data["total_assets"] - self._data["total_liabilities"], 2)
        self._status.setText(
            f"As of: {as_of}  |  "
            f"Assets: {_fmt(self._data['total_assets'])}  |  "
            f"Liabilities: {_fmt(self._data['total_liabilities'])}  |  "
            f"Diff: {_fmt(diff)}"
        )

    def _do_excel(self, exp, path):
        exp.balance_sheet(self._data, self.rpt.get_company(), path)

    def _do_pdf(self, exp, path):
        exp.balance_sheet(self._data, self.rpt.get_company(), path)


# ── shared: ledger book (cash / bank) ─────────────────────────────────────────

class _LedgerBookPage(_ReportBase):
    BOOK_TITLE   = "Book"
    SHOW_CLEARED = False    # Bank Book overrides → True (for reconciliation status)

    def _build_shell(self):
        super()._build_shell()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_widget = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_widget)
        self._scroll_layout.setSpacing(12)
        self._scroll_layout.addStretch()
        scroll.setWidget(self._scroll_widget)
        self._body.addWidget(scroll, 1)

    def _clear_scroll(self):
        while self._scroll_layout.count() > 1:
            item = self._scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_book_section(self, book: dict):
        frame = QFrame()
        frame.setObjectName("card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        title = QLabel(book["ledger"])
        title.setStyleSheet("font-weight:bold; font-size:13px;")
        lay.addWidget(title)

        opening = QLabel(f"Opening Balance:  {_fmt(book['opening'])}")
        opening.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
        lay.addWidget(opening)

        headers = ["Date","Voucher No","Type","Narration","Ref","Dr","Cr","Balance"]
        if self.SHOW_CLEARED:
            headers.append("Cleared")
        t = _make_table(headers, stretch_cols=[3])
        for tx in book["transactions"]:
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, _item(tx["date"]))
            t.setItem(r, 1, _item(tx["voucher_no"]))
            t.setItem(r, 2, _item(tx["voucher_type"].replace("_"," ")))
            t.setItem(r, 3, _item(tx["narration"]))
            t.setItem(r, 4, _item(tx["reference"]))
            t.setItem(r, 5, _item(_fmt(tx["dr"]) if tx["dr"] else "", right=True,
                                  colour=THEME["accent"] if tx["dr"] else None))
            t.setItem(r, 6, _item(_fmt(tx["cr"]) if tx["cr"] else "", right=True,
                                  colour=THEME["warning"] if tx["cr"] else None))
            bal_col = THEME["success"] if tx["balance"] >= 0 else THEME["danger"]
            t.setItem(r, 7, _item(_fmt(tx["balance"]), right=True, colour=bal_col))
            if self.SHOW_CLEARED:
                cleared = bool(tx.get("cleared"))
                t.setItem(r, 8, _item(
                    "✓" if cleared else "",
                    colour=THEME["success"] if cleared else None,
                ))
        lay.addWidget(t)

        closing = QLabel(f"Closing Balance:  {_fmt(book['closing'])}")
        closing.setStyleSheet("font-weight:bold; font-size:12px;")
        lay.addWidget(closing)

        insert_pos = self._scroll_layout.count() - 1
        self._scroll_layout.insertWidget(insert_pos, frame)

    def refresh(self):
        fd, td = self._dates()
        self._data = self._fetch(fd, td)
        self._clear_scroll()
        for book in self._data["books"]:
            self._add_book_section(book)
        n = sum(len(b["transactions"]) for b in self._data["books"])
        self._status.setText(
            f"{len(self._data['books'])} ledger(s)  |  {n} transactions"
        )

    def _fetch(self, fd, td): raise NotImplementedError

    def _do_excel(self, exp, path):
        exp.ledger_book(self._data, self.rpt.get_company(), self.BOOK_TITLE, path)

    def _do_pdf(self, exp, path):
        exp.ledger_book(self._data, self.rpt.get_company(), self.BOOK_TITLE, path)


class CashBookPage(_LedgerBookPage):
    TITLE      = "Cash Book"
    SUBTITLE   = "All transactions through cash ledgers"
    BOOK_TITLE = "Cash Book"

    def _fetch(self, fd, td):
        return self.rpt.cash_book(fd, td)


class BankBookPage(_LedgerBookPage):
    SHOW_CLEARED = True
    TITLE      = "Bank Book"
    SUBTITLE   = "All transactions through bank ledgers"
    BOOK_TITLE = "Bank Book"

    def _fetch(self, fd, td):
        return self.rpt.bank_book(fd, td)


# ── 7. Receipts & Payments ────────────────────────────────────────────────────

class ReceiptsPaymentsPage(_ReportBase):
    TITLE    = "Receipts & Payments"
    SUBTITLE = "Voucher-type summary for the period"

    def _build_shell(self):
        super()._build_shell()
        self._table = _make_table(
            ["Voucher Type","Count","Total Amount"],
            stretch_cols=[0]
        )
        self._body.addWidget(self._table, 1)

    def refresh(self):
        fd, td = self._dates()
        self._data = self.rpt.receipts_payments(fd, td)
        rows = [
            ("Receipts",         self._data["receipts"]),
            ("Payments",         self._data["payments"]),
            ("Sales",            self._data["sales"]),
            ("Purchases",        self._data["purchases"]),
            ("Journal Entries",  self._data["journals"]),
            ("Contra",           self._data["contras"]),
        ]
        self._table.setRowCount(len(rows))
        for i, (label, d) in enumerate(rows):
            colour = VOUCHER_COLOURS.get(label.upper().replace(" ","_"),
                                         THEME["text_secondary"])
            self._table.setItem(i, 0, _item(label, colour=colour))
            self._table.setItem(i, 1, _item(str(d["count"]), right=True))
            self._table.setItem(i, 2, _item(_fmt(d["total"]), right=True))
        total = sum(d["total"] for _, d in rows)
        self._status.setText(
            f"Period: {fd}  →  {td}  |  Total activity: {_fmt(total)}"
        )

    def _do_excel(self, exp, path):
        exp.receipts_payments(self._data, self.rpt.get_company(), path)

    def _do_pdf(self, exp, path):
        exp.receipts_payments(self._data, self.rpt.get_company(), path)


# ── 8. GST Summary ────────────────────────────────────────────────────────────

class GSTSummaryPage(_ReportBase):
    TITLE    = "GST Returns"
    SUBTITLE = "GSTR-1 / GSTR-3B summary — output tax, ITC, and net payable"

    def _build_shell(self):
        super()._build_shell()
        self._table = _make_table(
            ["Tax Type","Rate %","Output Tax","Input Tax (ITC)","Net"],
            stretch_cols=[0]
        )
        self._body.addWidget(self._table, 1)

        # Summary cards
        sum_bar = QFrame()
        sum_bar.setObjectName("card")
        sum_row = QHBoxLayout(sum_bar)
        sum_row.setContentsMargins(18, 10, 18, 10)
        sum_row.setSpacing(32)

        for attr, label, colour in [
            ("_lbl_output",   "Output Tax",     THEME["danger"]),
            ("_lbl_input",    "ITC (Input Tax)", THEME["success"]),
            ("_lbl_net",      "Net GST Payable", THEME["warning"]),
            ("_lbl_sales",    "Sales Base",      THEME["text_secondary"]),
            ("_lbl_purchase", "Purchase Base",   THEME["text_secondary"]),
        ]:
            col = QVBoxLayout()
            col.setSpacing(2)
            l = QLabel(label)
            l.setStyleSheet(f"font-size:10px; color:{THEME['text_dim']};")
            v = QLabel("₹0.00")
            v.setStyleSheet(f"font-size:14px; font-weight:bold; color:{colour};")
            col.addWidget(l)
            col.addWidget(v)
            sum_row.addLayout(col)
            setattr(self, attr, v)
        sum_row.addStretch()
        self._body.addWidget(sum_bar)

    def refresh(self):
        fd, td = self._dates()
        self._data = self.rpt.gst_summary(fd, td)
        rows = self._data["tax_lines"]
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            net = round(r["output_tax"] - r["input_tax"], 2)
            self._table.setItem(i, 0, _item(r["tax_type"]))
            self._table.setItem(i, 1, _item(f"{r['tax_rate']}%", right=True))
            self._table.setItem(i, 2, _item(_fmt(r["output_tax"]), right=True,
                                             colour=THEME["danger"]))
            self._table.setItem(i, 3, _item(_fmt(r["input_tax"]),  right=True,
                                             colour=THEME["success"]))
            net_col = THEME["danger"] if net > 0 else THEME["success"]
            self._table.setItem(i, 4, _item(_fmt(net), right=True, colour=net_col))

        self._lbl_output.setText(_fmt(self._data["total_output"]))
        self._lbl_input.setText(_fmt(self._data["total_input"]))
        self._lbl_net.setText(_fmt(self._data["net_gst_payable"]))
        self._lbl_sales.setText(_fmt(self._data["sales_base"]))
        self._lbl_purchase.setText(_fmt(self._data["purchase_base"]))
        self._status.setText(f"Period: {fd}  →  {td}")

    def _do_excel(self, exp, path):
        exp.gst_summary(self._data, self.rpt.get_company(), path)

    def _do_pdf(self, exp, path):
        exp.gst_summary(self._data, self.rpt.get_company(), path)


# ── 9. TDS Report ─────────────────────────────────────────────────────────────

class TDSReportPage(_ReportBase):
    TITLE    = "TDS Reports"
    SUBTITLE = "TDS deducted — 26Q / 27Q summary"

    def _build_shell(self):
        super()._build_shell()
        self._table = _make_table(
            ["Rate %","TDS Amount","Voucher Count"],
            stretch_cols=[0]
        )
        self._body.addWidget(self._table, 1)

    def refresh(self):
        fd, td = self._dates()
        self._data = self.rpt.tds_report(fd, td)
        rows = self._data["tds_lines"]
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self._table.setItem(i, 0, _item(f"{r['tax_rate']}%", right=True))
            self._table.setItem(i, 1, _item(_fmt(r["tds_amount"]), right=True,
                                             colour=THEME["warning"]))
            self._table.setItem(i, 2, _item(str(r["voucher_count"]), right=True))
        self._status.setText(
            f"Period: {fd}  →  {td}  |  "
            f"Total TDS: {_fmt(self._data['total_tds'])}"
        )

    def _do_excel(self, exp, path):
        exp.tds_report(self._data, self.rpt.get_company(), path)

    def _do_pdf(self, exp, path):
        exp.tds_report(self._data, self.rpt.get_company(), path)


# ── Ledger Account (per-ledger statement view) ───────────────────────────────

class LedgerAccountPage(_ReportBase):
    """
    Per-ledger statement view. Pick any ledger, see the running-balance
    transaction list. For bank ledgers, a 'Cleared' (✓) column shows
    reconciliation status. Click a row to open the voucher detail dialog.
    """
    TITLE    = "Ledger Account"
    SUBTITLE = ""

    def __init__(self, rpt, tree, engine, parent=None):
        self.tree   = tree
        self.engine = engine
        super().__init__(rpt, parent)

    def _build_shell(self):
        """
        Override the parent shell entirely — give the body the maximum
        vertical space by collapsing title + ledger picker + dates +
        export buttons into one dense row.
        """
        from ui.widgets import LedgerSearchEdit

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 6, 20, 14)
        root.setSpacing(6)

        bar = QFrame()
        bar.setObjectName("card")
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(10)

        title = QLabel("📒 Ledger Account")
        title.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['text_primary']};"
        )
        h.addWidget(title)

        h.addSpacing(6)

        self._ledger_picker = LedgerSearchEdit(
            self.tree, calculator=None,
            placeholder="Pick a ledger…",
        )
        self._ledger_picker.setFixedWidth(260)
        self._ledger_picker.ledger_selected.connect(lambda *_: self.refresh())
        h.addWidget(self._ledger_picker)

        h.addSpacing(8)
        h.addWidget(make_label("From"))
        self.from_date = SmartDateEdit(_fy_start())
        self.from_date.setDisplayFormat("dd-MMM-yyyy")
        self.from_date.setFixedHeight(28)
        h.addWidget(self.from_date)

        h.addWidget(make_label("To"))
        self.to_date = SmartDateEdit(QDate.currentDate())
        self.to_date.setDisplayFormat("dd-MMM-yyyy")
        self.to_date.setFixedHeight(28)
        h.addWidget(self.to_date)

        h.addStretch()

        ref_btn = QPushButton("↻ Refresh")
        ref_btn.setFixedHeight(28)
        ref_btn.clicked.connect(self.refresh)
        h.addWidget(ref_btn)

        xl_btn = QPushButton("⬇ Excel")
        xl_btn.setFixedHeight(28)
        xl_btn.clicked.connect(self._save_excel)
        h.addWidget(xl_btn)

        pdf_btn = QPushButton("⬇ PDF")
        pdf_btn.setFixedHeight(28)
        pdf_btn.clicked.connect(self._save_pdf)
        h.addWidget(pdf_btn)

        root.addWidget(bar)

        # Body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_widget = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_widget)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(8)
        self._scroll_layout.addStretch()
        scroll.setWidget(self._scroll_widget)
        root.addWidget(scroll, 1)

        # Status
        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        root.addWidget(self._status)

        # Body layout reference for compatibility with parent's hooks
        self._body = root

    def _clear_scroll(self):
        while self._scroll_layout.count() > 1:
            item = self._scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def refresh(self):
        self._clear_scroll()
        fd, td = self._dates()
        ledger_id = self._ledger_picker.selected_id
        if not ledger_id:
            self._status.setText("Pick a ledger to view its account.")
            return

        self._data = self.rpt.ledger_account(ledger_id, fd, td)
        if not self._data:
            self._status.setText("Ledger not found.")
            return

        self._render_book(self._data)
        n = len(self._data["transactions"])
        self._status.setText(
            f"{self._data['ledger']}  ·  {self._data['group']}  ·  "
            f"Period: {fd} → {td}  ·  {n} transaction(s)  ·  "
            f"Net: {_fmt(self._data['closing'] - self._data['opening'])}"
        )

    def _render_book(self, data: dict):
        frame = QFrame()
        frame.setObjectName("card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        # Header
        title_row = QHBoxLayout()
        title = QLabel(data["ledger"])
        title.setStyleSheet("font-weight:bold; font-size:14px;")
        title_row.addWidget(title)

        meta_bits = [data["group"]]
        if data.get("account_number"):
            meta_bits.append(f"A/C {data['account_number']}")
        if data.get("bank_name"):
            meta_bits.append(data["bank_name"])
        meta = QLabel("  ·  ".join(meta_bits))
        meta.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding-left:8px;"
        )
        title_row.addWidget(meta)
        title_row.addStretch()
        lay.addLayout(title_row)

        opening = QLabel(f"Opening Balance:  {_fmt(data['opening'])}")
        opening.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
        lay.addWidget(opening)

        # Table
        show_cleared = bool(data.get("is_bank"))
        headers = ["Date", "Voucher No", "Type", "Narration", "Ref", "Dr", "Cr", "Balance"]
        if show_cleared:
            headers.append("Cleared")
        t = _make_table(headers, stretch_cols=[3])
        # Map row index → voucher_id, for click-to-open
        row_to_voucher: dict[int, int] = {}
        for tx in data["transactions"]:
            r = t.rowCount()
            t.insertRow(r)
            row_to_voucher[r] = tx["voucher_id"]
            t.setItem(r, 0, _item(tx["date"]))
            t.setItem(r, 1, _item(tx["voucher_no"]))
            t.setItem(r, 2, _item(tx["type"].replace("_", " ")))
            t.setItem(r, 3, _item(tx["narration"]))
            t.setItem(r, 4, _item(tx["reference"]))
            t.setItem(r, 5, _item(_fmt(tx["dr"]) if tx["dr"] else "", right=True,
                                  colour=THEME["accent"] if tx["dr"] else None))
            t.setItem(r, 6, _item(_fmt(tx["cr"]) if tx["cr"] else "", right=True,
                                  colour=THEME["warning"] if tx["cr"] else None))
            bal_col = THEME["success"] if tx["balance"] >= 0 else THEME["danger"]
            t.setItem(r, 7, _item(_fmt(tx["balance"]), right=True, colour=bal_col))
            if show_cleared:
                cleared = bool(tx.get("cleared"))
                t.setItem(r, 8, _item(
                    "✓" if cleared else "",
                    colour=THEME["success"] if cleared else None,
                ))
        # Open voucher detail on double-click (deliberate; single click is selection)
        t.cellDoubleClicked.connect(
            lambda row, _col, m=row_to_voucher: self._open_voucher(m.get(row))
        )
        t.setToolTip("Double-click a row to open the voucher")
        lay.addWidget(t)

        closing = QLabel(f"Closing Balance:  {_fmt(data['closing'])}")
        closing.setStyleSheet("font-weight:bold; font-size:12px;")
        lay.addWidget(closing)

        insert_pos = self._scroll_layout.count() - 1
        self._scroll_layout.insertWidget(insert_pos, frame)

    def _open_voucher(self, voucher_id):
        """Open the voucher in the main Post Voucher form (edit mode)."""
        if not voucher_id:
            return
        # Walk up to MainWindow which owns the voucher form.
        win = self.window()
        if hasattr(win, "open_voucher_for_edit"):
            win.open_voucher_for_edit(voucher_id)

    # Excel / PDF — wrap into the ledger_book exporter's expected shape.
    def _wrap_for_export(self) -> dict:
        return {
            "books": [{
                "ledger":       self._data["ledger"],
                "opening":      self._data["opening"],
                "transactions": self._data["transactions"],
                "closing":      self._data["closing"],
            }],
            "from_date": self._data["from_date"],
            "to_date":   self._data["to_date"],
        }

    def _do_excel(self, exp, path):
        if not self._data:
            return
        exp.ledger_book(self._wrap_for_export(), self.rpt.get_company(),
                        f"Ledger - {self._data['ledger']}", path)

    def _do_pdf(self, exp, path):
        if not self._data:
            return
        exp.ledger_book(self._wrap_for_export(), self.rpt.get_company(),
                        f"Ledger - {self._data['ledger']}", path)
