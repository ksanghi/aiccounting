"""
Exporters — Excel (openpyxl) and PDF (reportlab) export for all reports.
Both classes degrade gracefully if the library is not installed.
"""
import os


def _fmt(v: float) -> str:
    return f"{v:,.2f}"


# ── Excel ─────────────────────────────────────────────────────────────────────

class ExcelExporter:

    def __init__(self):
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
            self._xl   = openpyxl
            self._Font = Font
            self._Fill = PatternFill
            self._Aln  = Alignment
            self.available = True
        except ImportError:
            self.available = False

    # shared helpers
    def _wb(self, title: str):
        wb = self._xl.Workbook()
        ws = wb.active
        ws.title = title
        return wb, ws

    def _header(self, ws, company: dict, subtitle: str, row: int = 1):
        ws.cell(row, 1, company.get("name", "Company")).font = self._Font(bold=True, size=13)
        ws.cell(row+1, 1, subtitle).font = self._Font(bold=True, size=10)
        return row + 3  # next usable row

    def _col_hdrs(self, ws, row: int, headers: list):
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row, c, h)
            cell.font = self._Font(bold=True, color="FFFFFF")
            cell.fill = self._Fill("solid", fgColor="1A3A5C")
        return row + 1

    def _set_widths(self, ws, widths: list):
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[
                self._xl.utils.get_column_letter(i)
            ].width = w

    # ── reports ──────────────────────────────────────────────────────────────

    def trial_balance(self, data: list, company: dict, as_of: str, path: str):
        wb, ws = self._wb("Trial Balance")
        r = self._header(ws, company, f"Trial Balance as on {as_of}")
        r = self._col_hdrs(ws, r, [
            "#","Ledger","Group","Nature","Op Dr","Op Cr","Txn Dr","Txn Cr","Cl Dr","Cl Cr"
        ])
        for i, d in enumerate(data, 1):
            ws.append([i, d["ledger"], d["group"], d["nature"],
                       d["opening_dr"], d["opening_cr"],
                       d["txn_dr"],    d["txn_cr"],
                       d["closing_dr"],d["closing_cr"]])
        ws.append(["","TOTAL","","",
            sum(d["opening_dr"] for d in data), sum(d["opening_cr"] for d in data),
            sum(d["txn_dr"]     for d in data), sum(d["txn_cr"]     for d in data),
            sum(d["closing_dr"] for d in data), sum(d["closing_cr"] for d in data),
        ])
        self._set_widths(ws, [4,30,22,10,14,14,14,14,14,14])
        wb.save(path)

    def profit_and_loss(self, data: dict, company: dict, path: str):
        wb, ws = self._wb("P and L")
        r = self._header(ws, company, f"Profit & Loss: {data['from_date']} to {data['to_date']}")
        r = self._col_hdrs(ws, r, ["Section","Ledger","Amount (Rs)"])
        for d in data["income"]:
            ws.append(["Income", d["ledger"], d["amount"]])
        ws.append(["","Total Income", data["total_income"]])
        for d in data["expenses"]:
            ws.append(["Expense", d["ledger"], d["amount"]])
        ws.append(["","Total Expenses", data["total_expense"]])
        ws.append(["","Net Profit / (Loss)", data["net_profit"]])
        self._set_widths(ws, [12,36,16])
        wb.save(path)

    def balance_sheet(self, data: dict, company: dict, path: str):
        wb, ws = self._wb("Balance Sheet")
        r = self._header(ws, company, f"Balance Sheet as on {data['as_of']}")
        r = self._col_hdrs(ws, r, ["Assets","Amount","Liabilities","Amount"])
        assets = data["assets"]
        liabs  = data["liabilities"]
        for i in range(max(len(assets), len(liabs))):
            a = assets[i] if i < len(assets) else {}
            l = liabs[i]  if i < len(liabs)  else {}
            ws.append([
                a.get("ledger",""), a["balance"] if a else "",
                l.get("ledger",""), l["balance"] if l else "",
            ])
        ws.append(["Total Assets", data["total_assets"], "Total Liabilities", data["total_liabilities"]])
        self._set_widths(ws, [30,14,30,14])
        wb.save(path)

    def ledger_book(self, data: dict, company: dict, title: str, path: str):
        wb = self._xl.Workbook()
        wb.remove(wb.active)
        for book in data["books"]:
            ws = wb.create_sheet(book["ledger"][:28])
            r = self._header(ws, company, f"{title}: {book['ledger']} ({data['from_date']} to {data['to_date']})")
            ws.append(["Opening Balance","","","","","", book["opening"]])
            r = self._col_hdrs(ws, r+1, ["Date","Voucher","Type","Narration","Ref","Dr","Cr","Balance"])
            for t in book["transactions"]:
                ws.append([t["date"], t["voucher_no"], t["voucher_type"],
                           t["narration"], t["reference"],
                           t["dr"] or "", t["cr"] or "", t["balance"]])
            ws.append(["Closing Balance","","","","","","", book["closing"]])
            self._set_widths(ws, [12,14,8,30,14,12,12,14])
        wb.save(path)

    def receipts_payments(self, data: dict, company: dict, path: str):
        wb, ws = self._wb("Receipts and Payments")
        r = self._header(ws, company, f"Receipts & Payments: {data['from_date']} to {data['to_date']}")
        r = self._col_hdrs(ws, r, ["Voucher Type","Count","Amount (Rs)"])
        for key, label in [
            ("receipts","Receipts"), ("payments","Payments"), ("sales","Sales"),
            ("purchases","Purchases"), ("journals","Journal Entries"), ("contras","Contra"),
        ]:
            d = data[key]
            ws.append([label, d["count"], d["total"]])
        self._set_widths(ws, [24,10,18])
        wb.save(path)

    def gst_summary(self, data: dict, company: dict, path: str):
        wb, ws = self._wb("GST Summary")
        r = self._header(ws, company, f"GST Summary: {data['from_date']} to {data['to_date']}")
        r = self._col_hdrs(ws, r, ["Tax Type","Rate %","Output Tax","Input Tax (ITC)"])
        for row in data["tax_lines"]:
            ws.append([row["tax_type"], row["tax_rate"], row["output_tax"], row["input_tax"]])
        ws.append(["Total","", data["total_output"], data["total_input"]])
        ws.append(["Net GST Payable","","", data["net_gst_payable"]])
        ws.append([])
        ws.append(["Sales Base Value", data["sales_base"]])
        ws.append(["Purchase Base Value", data["purchase_base"]])
        self._set_widths(ws, [14,10,18,18])
        wb.save(path)

    def tds_report(self, data: dict, company: dict, path: str):
        wb, ws = self._wb("TDS Report")
        r = self._header(ws, company, f"TDS Report: {data['from_date']} to {data['to_date']}")
        r = self._col_hdrs(ws, r, ["Rate %","TDS Amount","Voucher Count"])
        for row in data["tds_lines"]:
            ws.append([row["tax_rate"], row["tds_amount"], row["voucher_count"]])
        ws.append(["Total TDS", data["total_tds"], ""])
        self._set_widths(ws, [12,18,14])
        wb.save(path)


# ── PDF ───────────────────────────────────────────────────────────────────────

class PDFExporter:

    _HDR_COLOR  = (0x1A/255, 0x3A/255, 0x5C/255)
    _ROW_COLORS = ((1,1,1), (0.95,0.97,1.0))

    def __init__(self):
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import cm
            from reportlab.platypus import (
                SimpleDocTemplate, Table, TableStyle,
                Paragraph, Spacer
            )
            self._A4         = A4
            self._landscape  = landscape
            self._colors     = colors
            self._styles     = getSampleStyleSheet()
            self._cm         = cm
            self._Doc        = SimpleDocTemplate
            self._Table      = Table
            self._TStyle     = TableStyle
            self._Para       = Paragraph
            self._Spacer     = Spacer
            self.available   = True
        except ImportError:
            self.available   = False

    def _doc(self, path: str, wide: bool = False):
        size = self._landscape(self._A4) if wide else self._A4
        cm = self._cm
        return self._Doc(path, pagesize=size,
                         topMargin=1.5*cm, bottomMargin=1.5*cm,
                         leftMargin=1.5*cm, rightMargin=1.5*cm)

    def _tbl_style(self):
        c = self._colors
        return self._TStyle([
            ("BACKGROUND",  (0,0), (-1,0),  c.HexColor("#1A3A5C")),
            ("TEXTCOLOR",   (0,0), (-1,0),  c.white),
            ("FONTNAME",    (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",    (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[c.white, c.HexColor("#EFF3F8")]),
            ("GRID",        (0,0), (-1,-1), 0.25, c.HexColor("#C0C8D0")),
            ("TOPPADDING",  (0,0), (-1,-1), 3),
            ("BOTTOMPADDING",(0,0),(-1,-1), 3),
            ("LEFTPADDING", (0,0), (-1,-1), 5),
        ])

    def _heading(self, company: dict, subtitle: str) -> list:
        s = self._styles
        return [
            self._Para(company.get("name","Company"), s["Title"]),
            self._Para(subtitle, s["Normal"]),
            self._Spacer(1, 0.35*self._cm),
        ]

    def trial_balance(self, data: list, company: dict, as_of: str, path: str):
        cm = self._cm
        doc = self._doc(path, wide=True)
        elems = self._heading(company, f"Trial Balance as on {as_of}")
        hdrs = ["#","Ledger","Group","Nat","Op Dr","Op Cr","Txn Dr","Txn Cr","Cl Dr","Cl Cr"]
        rows = [hdrs]
        for i, d in enumerate(data, 1):
            rows.append([str(i), d["ledger"][:26], d["group"][:18], d["nature"][:3],
                _fmt(d["opening_dr"]), _fmt(d["opening_cr"]),
                _fmt(d["txn_dr"]),    _fmt(d["txn_cr"]),
                _fmt(d["closing_dr"]),_fmt(d["closing_cr"])])
        rows.append(["","TOTAL","","",
            _fmt(sum(d["opening_dr"] for d in data)), _fmt(sum(d["opening_cr"] for d in data)),
            _fmt(sum(d["txn_dr"]     for d in data)), _fmt(sum(d["txn_cr"]     for d in data)),
            _fmt(sum(d["closing_dr"] for d in data)), _fmt(sum(d["closing_cr"] for d in data)),
        ])
        cw = [0.5*cm,4.2*cm,3.2*cm,1.2*cm,2.5*cm,2.5*cm,2.5*cm,2.5*cm,2.5*cm,2.5*cm]
        t = self._Table(rows, colWidths=cw)
        t.setStyle(self._tbl_style())
        elems.append(t)
        doc.build(elems)

    def profit_and_loss(self, data: dict, company: dict, path: str):
        cm = self._cm
        doc = self._doc(path)
        elems = self._heading(company, f"P&L: {data['from_date']} to {data['to_date']}")
        rows = [["Section","Ledger","Amount (Rs)"]]
        for d in data["income"]:
            rows.append(["Income", d["ledger"][:38], _fmt(d["amount"])])
        rows.append(["","Total Income", _fmt(data["total_income"])])
        for d in data["expenses"]:
            rows.append(["Expense", d["ledger"][:38], _fmt(d["amount"])])
        rows.append(["","Total Expenses", _fmt(data["total_expense"])])
        rows.append(["","Net Profit / (Loss)", _fmt(data["net_profit"])])
        cw = [2.5*cm, 9*cm, 4*cm]
        t = self._Table(rows, colWidths=cw)
        t.setStyle(self._tbl_style())
        elems.append(t)
        doc.build(elems)

    def balance_sheet(self, data: dict, company: dict, path: str):
        cm = self._cm
        doc = self._doc(path, wide=True)
        elems = self._heading(company, f"Balance Sheet as on {data['as_of']}")
        rows = [["Assets","Amount","Liabilities","Amount"]]
        a_list = data["assets"]
        l_list = data["liabilities"]
        for i in range(max(len(a_list), len(l_list))):
            a = a_list[i] if i < len(a_list) else {}
            l = l_list[i] if i < len(l_list) else {}
            rows.append([
                a.get("ledger","")[:30], _fmt(a["balance"]) if a else "",
                l.get("ledger","")[:30], _fmt(l["balance"]) if l else "",
            ])
        rows.append(["Total Assets", _fmt(data["total_assets"]),
                     "Total Liabilities", _fmt(data["total_liabilities"])])
        cw = [6*cm, 3.5*cm, 6*cm, 3.5*cm]
        t = self._Table(rows, colWidths=cw)
        t.setStyle(self._tbl_style())
        elems.append(t)
        doc.build(elems)

    def ledger_book(self, data: dict, company: dict, title: str, path: str):
        cm = self._cm
        doc = self._doc(path, wide=True)
        elems = self._heading(company, f"{title}: {data['from_date']} to {data['to_date']}")
        for book in data["books"]:
            elems.append(self._Para(book["ledger"], self._styles["Heading2"]))
            rows = [["Date","Voucher","Type","Narration","Ref","Dr","Cr","Balance"]]
            rows.append(["Opening","","","","","","",_fmt(book["opening"])])
            for t in book["transactions"]:
                rows.append([
                    t["date"], t["voucher_no"], t["voucher_type"][:3],
                    t["narration"][:28], t["reference"][:10],
                    _fmt(t["dr"]) if t["dr"] else "",
                    _fmt(t["cr"]) if t["cr"] else "",
                    _fmt(t["balance"]),
                ])
            rows.append(["Closing","","","","","","",_fmt(book["closing"])])
            cw = [2*cm,3*cm,1.2*cm,6*cm,2.5*cm,2.5*cm,2.5*cm,2.8*cm]
            tbl = self._Table(rows, colWidths=cw)
            tbl.setStyle(self._tbl_style())
            elems += [tbl, self._Spacer(1, 0.5*cm)]
        doc.build(elems)

    def receipts_payments(self, data: dict, company: dict, path: str):
        cm = self._cm
        doc = self._doc(path)
        elems = self._heading(company, f"Receipts & Payments: {data['from_date']} to {data['to_date']}")
        rows = [["Voucher Type","Count","Amount (Rs)"]]
        for key, label in [
            ("receipts","Receipts"), ("payments","Payments"), ("sales","Sales"),
            ("purchases","Purchases"), ("journals","Journal Entries"), ("contras","Contra"),
        ]:
            d = data[key]
            rows.append([label, str(d["count"]), _fmt(d["total"])])
        cw = [6*cm, 3*cm, 5*cm]
        t = self._Table(rows, colWidths=cw)
        t.setStyle(self._tbl_style())
        elems.append(t)
        doc.build(elems)

    def gst_summary(self, data: dict, company: dict, path: str):
        cm = self._cm
        doc = self._doc(path)
        elems = self._heading(company, f"GST Summary: {data['from_date']} to {data['to_date']}")
        rows = [["Tax Type","Rate %","Output Tax","ITC (Input)"]]
        for r in data["tax_lines"]:
            rows.append([r["tax_type"], f"{r['tax_rate']}%",
                         _fmt(r["output_tax"]), _fmt(r["input_tax"])])
        rows.append(["Total","",_fmt(data["total_output"]),_fmt(data["total_input"])])
        rows.append(["Net GST Payable","","",_fmt(data["net_gst_payable"])])
        rows.append(["Sales Base",_fmt(data["sales_base"]),"",""])
        rows.append(["Purchase Base",_fmt(data["purchase_base"]),"",""])
        cw = [3.5*cm,2.5*cm,5*cm,5*cm]
        t = self._Table(rows, colWidths=cw)
        t.setStyle(self._tbl_style())
        elems.append(t)
        doc.build(elems)

    def tds_report(self, data: dict, company: dict, path: str):
        cm = self._cm
        doc = self._doc(path)
        elems = self._heading(company, f"TDS Report: {data['from_date']} to {data['to_date']}")
        rows = [["Rate %","TDS Amount","Voucher Count"]]
        for r in data["tds_lines"]:
            rows.append([f"{r['tax_rate']}%", _fmt(r["tds_amount"]), str(r["voucher_count"])])
        rows.append(["Total TDS", _fmt(data["total_tds"]), ""])
        cw = [3*cm, 5*cm, 4*cm]
        t = self._Table(rows, colWidths=cw)
        t.setStyle(self._tbl_style())
        elems.append(t)
        doc.build(elems)
