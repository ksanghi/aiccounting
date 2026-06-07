"""
Bill-wise Outstanding report — the open-item (Tally "bill-by-bill") view.

Lists every OPEN bill (pending != 0), bill-by-bill, with its age, for either
Sundry Debtors (receivables) or Sundry Creditors (payables). Complements the
balance-based Receivables Aging report. Backed by core.bill_wise.BillWiseEngine.

Gated by the `bill_wise_refs` licence flag (PRO/PREMIUM) at registration in
ui/main_window. Reuses the shared _ReportBase shell (filter bar, free-text row
filter, Excel/PDF/print export).
"""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel, QFrame, QHBoxLayout

from ui.reports_page import _ReportBase, _make_table, _item, _fmt
from ui.table_utils  import make_sortable
from ui.theme        import THEME
from core.bill_wise  import BillWiseEngine


class BillWiseOutstandingPage(_ReportBase):
    TITLE    = "Bill-wise Outstanding"
    SUBTITLE = "Open bills, bill-by-bill, with aging (Against Reference)"
    AS_OF    = True

    def _build_shell(self):
        super()._build_shell()

        # Bucket summary strip
        self._bucket_bar = QFrame()
        self._bucket_bar.setObjectName("card")
        brow = QHBoxLayout(self._bucket_bar)
        brow.setContentsMargins(12, 8, 12, 8)
        brow.setSpacing(20)
        self._bucket_lbls = {}
        for key, title in (("b0_30", "0-30"), ("b31_60", "31-60"),
                           ("b61_90", "61-90"), ("b90p", "90+"),
                           ("total", "Total")):
            box = QHBoxLayout()
            cap = QLabel(title)
            cap.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
            val = QLabel("—")
            bold = "font-weight:bold;" if key == "total" else ""
            danger = f"color:{THEME['danger']};" if key == "b90p" else ""
            val.setStyleSheet(f"font-size:13px; {bold} {danger}")
            self._bucket_lbls[key] = val
            brow.addWidget(cap)
            brow.addWidget(val)
            brow.addSpacing(8)
        brow.addStretch()
        self._body.addWidget(self._bucket_bar)

        self._table = _make_table(
            ["Party", "Bill No", "Bill Date", "Age (days)",
             "Bill Amount", "Pending"],
            stretch_cols=[0],
        )
        self._body.addWidget(self._table, 1)

    def _extra_filters(self, row):
        row.addWidget(QLabel("Show"))
        self._grp = QComboBox()
        self._grp.addItem("Receivables (Debtors)", "Sundry Debtors")
        self._grp.addItem("Payables (Creditors)",  "Sundry Creditors")
        self._grp.setFixedHeight(30)
        self._grp.currentIndexChanged.connect(self.refresh)
        row.addWidget(self._grp)

    def refresh(self):
        as_of = self._dates()
        group = self._grp.currentData() if hasattr(self, "_grp") else "Sundry Debtors"
        bw = BillWiseEngine(self.rpt.db, self.rpt.company_id)
        self._data = bw.aging_by_bill(as_of, group)
        rows = self._data["rows"]

        t = self._table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, d in enumerate(rows):
            t.setItem(i, 0, _item(d["party"]))
            t.setItem(i, 1, _item(d["bill_number"] or "—"))
            t.setItem(i, 2, _item(d["bill_date"]))
            t.setItem(i, 3, _item(str(d["age_days"]), right=True))
            t.setItem(i, 4, _item(_fmt(d["bill_amount"]), right=True))
            t.setItem(i, 5, _item(
                _fmt(d["pending_amount"]), right=True, bold=True,
                colour=THEME["danger"] if d["bucket"] == "b90p" else None))
        # Flat list — sort + filter are safe (and required by the table rule).
        make_sortable(t)
        self._register_filter_target(t)

        b = self._data["buckets"]
        for k in ("b0_30", "b31_60", "b61_90", "b90p"):
            self._bucket_lbls[k].setText(_fmt(b[k]))
        self._bucket_lbls["total"].setText(_fmt(self._data["total"]))

        kind = "debtor" if group == "Sundry Debtors" else "creditor"
        self._status.setText(
            f"As on {as_of}  |  {len(rows)} open bill(s) across "
            f"{kind} accounts  |  Outstanding: {_fmt(self._data['total'])}"
        )

    def _do_excel(self, exp, path):
        exp.bill_wise_aging(self._data, self.rpt.get_company(), path)

    def _do_pdf(self, exp, path):
        exp.bill_wise_aging(self._data, self.rpt.get_company(), path)
