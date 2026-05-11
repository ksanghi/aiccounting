"""
Reports Engine — queries DB and returns structured data for all reports.
No UI code here.
"""
from .models import Database


class ReportsEngine:

    def __init__(self, db: Database, company_id: int):
        self.db = db
        self.company_id = company_id

    def get_company(self) -> dict:
        row = self.db.execute(
            "SELECT * FROM companies WHERE id=?", (self.company_id,)
        ).fetchone()
        return dict(row) if row else {}

    # ── 1. Trial Balance ──────────────────────────────────────────────────────

    def trial_balance(self, as_of: str) -> list[dict]:
        ledgers = self.db.execute(
            """SELECT l.id, l.name as ledger, g.name as grp, g.nature,
                      l.opening_balance, l.opening_type
               FROM ledgers l
               JOIN account_groups g ON l.group_id=g.id
               WHERE l.company_id=? AND l.active=1
               ORDER BY g.nature, g.name, l.name""",
            (self.company_id,)
        ).fetchall()

        rows = []
        for l in ledgers:
            txn = self.db.execute(
                """SELECT COALESCE(SUM(vl.dr_amount),0) as dr,
                          COALESCE(SUM(vl.cr_amount),0) as cr
                   FROM voucher_lines vl
                   JOIN vouchers v ON vl.voucher_id=v.id
                   WHERE vl.ledger_id=? AND v.is_cancelled=0
                     AND v.company_id=? AND v.voucher_date<=?""",
                (l["id"], self.company_id, as_of)
            ).fetchone()

            ob = l["opening_balance"]
            ot = l["opening_type"]
            ob_dr = ob if ot == "Dr" else 0.0
            ob_cr = ob if ot == "Cr" else 0.0
            txn_dr = txn["dr"] or 0.0
            txn_cr = txn["cr"] or 0.0
            net = (ob_dr + txn_dr) - (ob_cr + txn_cr)
            cl_dr = round(net, 2) if net >= 0 else 0.0
            cl_cr = round(-net, 2) if net < 0 else 0.0

            if ob_dr or ob_cr or txn_dr or txn_cr:
                rows.append({
                    "ledger":     l["ledger"],
                    "group":      l["grp"],
                    "nature":     l["nature"],
                    "opening_dr": round(ob_dr, 2),
                    "opening_cr": round(ob_cr, 2),
                    "txn_dr":     round(txn_dr, 2),
                    "txn_cr":     round(txn_cr, 2),
                    "closing_dr": cl_dr,
                    "closing_cr": cl_cr,
                })
        return rows

    # ── 2. Profit & Loss ──────────────────────────────────────────────────────

    def profit_and_loss(self, from_date: str, to_date: str) -> dict:
        def ledger_net(nature: str) -> list[dict]:
            rows = self.db.execute(
                """SELECT l.name as ledger, g.name as grp,
                          COALESCE(SUM(vl.dr_amount),0) as dr,
                          COALESCE(SUM(vl.cr_amount),0) as cr
                   FROM voucher_lines vl
                   JOIN vouchers v ON vl.voucher_id=v.id
                   JOIN ledgers l ON vl.ledger_id=l.id
                   JOIN account_groups g ON l.group_id=g.id
                   WHERE v.company_id=? AND v.is_cancelled=0
                     AND v.voucher_date BETWEEN ? AND ?
                     AND g.nature=?
                   GROUP BY l.id, l.name, g.name
                   HAVING (dr+cr)>0
                   ORDER BY g.name, l.name""",
                (self.company_id, from_date, to_date, nature)
            ).fetchall()
            return [dict(r) for r in rows]

        income_rows   = ledger_net("INCOME")
        expense_rows  = ledger_net("EXPENSE")
        for r in income_rows:
            r["group"] = r.pop("grp")
            r["amount"] = round(r["cr"] - r["dr"], 2)
        for r in expense_rows:
            r["group"] = r.pop("grp")
            r["amount"] = round(r["dr"] - r["cr"], 2)

        total_income  = round(sum(r["amount"] for r in income_rows),  2)
        total_expense = round(sum(r["amount"] for r in expense_rows), 2)
        return {
            "income":        income_rows,
            "expenses":      expense_rows,
            "total_income":  total_income,
            "total_expense": total_expense,
            "net_profit":    round(total_income - total_expense, 2),
            "from_date":     from_date,
            "to_date":       to_date,
        }

    # ── 3. Balance Sheet ──────────────────────────────────────────────────────

    def balance_sheet(self, as_of: str) -> dict:
        def get_balances(nature: str) -> list[dict]:
            rows = self.db.execute(
                """SELECT l.id, l.name as ledger, g.name as grp,
                          l.opening_balance, l.opening_type
                   FROM ledgers l
                   JOIN account_groups g ON l.group_id=g.id
                   WHERE l.company_id=? AND g.nature=? AND l.active=1
                   ORDER BY g.name, l.name""",
                (self.company_id, nature)
            ).fetchall()
            result = []
            for l in rows:
                txn = self.db.execute(
                    """SELECT COALESCE(SUM(vl.dr_amount),0) as dr,
                              COALESCE(SUM(vl.cr_amount),0) as cr
                       FROM voucher_lines vl
                       JOIN vouchers v ON vl.voucher_id=v.id
                       WHERE vl.ledger_id=? AND v.is_cancelled=0
                         AND v.company_id=? AND v.voucher_date<=?""",
                    (l["id"], self.company_id, as_of)
                ).fetchone()
                ob = l["opening_balance"]
                ot = l["opening_type"]
                ob_dr = ob if ot == "Dr" else 0.0
                ob_cr = ob if ot == "Cr" else 0.0
                txn_dr = txn["dr"] or 0.0
                txn_cr = txn["cr"] or 0.0
                net = (ob_dr + txn_dr) - (ob_cr + txn_cr)
                balance = abs(net)
                if balance > 0.001:
                    result.append({
                        "ledger":  l["ledger"],
                        "group":   l["grp"],
                        "balance": round(balance, 2),
                        "side":    "Dr" if net >= 0 else "Cr",
                    })
            return result

        assets      = get_balances("ASSET")
        liabilities = get_balances("LIABILITY")

        # A ledger whose balance lands on the side opposite its group's
        # natural side (e.g. a bank overdraft → Asset nature with Cr balance,
        # or a vendor advance refund → Liability with Dr balance) must
        # *reduce* its side's total, not be dropped. Treat such balances as
        # signed contributions.
        def signed_total(rows: list[dict], natural_side: str) -> float:
            return sum(
                r["balance"] if r["side"] == natural_side else -r["balance"]
                for r in rows
            )

        return {
            "assets":            assets,
            "liabilities":       liabilities,
            "total_assets":      round(signed_total(assets,      "Dr"), 2),
            "total_liabilities": round(signed_total(liabilities, "Cr"), 2),
            "as_of":             as_of,
        }

    # ── 4 & 5. Cash Book / Bank Book ─────────────────────────────────────────

    def cash_book(self, from_date: str, to_date: str) -> dict:
        return self._ledger_book(from_date, to_date, flag_col="is_cash")

    def bank_book(self, from_date: str, to_date: str) -> dict:
        return self._ledger_book(from_date, to_date, flag_col="is_bank")

    def _ledger_book(self, from_date: str, to_date: str, flag_col: str) -> dict:
        ledgers = self.db.execute(
            f"SELECT id, name FROM ledgers WHERE company_id=? AND {flag_col}=1 AND active=1",
            (self.company_id,)
        ).fetchall()
        books = []
        for ldg in ledgers:
            ob_txn = self.db.execute(
                """SELECT COALESCE(SUM(vl.dr_amount),0) as dr,
                          COALESCE(SUM(vl.cr_amount),0) as cr
                   FROM voucher_lines vl
                   JOIN vouchers v ON vl.voucher_id=v.id
                   WHERE vl.ledger_id=? AND v.is_cancelled=0
                     AND v.company_id=? AND v.voucher_date < ?""",
                (ldg["id"], self.company_id, from_date)
            ).fetchone()
            l_info = self.db.execute(
                "SELECT opening_balance, opening_type FROM ledgers WHERE id=?", (ldg["id"],)
            ).fetchone()
            ob = l_info["opening_balance"] if l_info else 0.0
            ot = l_info["opening_type"]    if l_info else "Dr"
            ob_dr = ob if ot == "Dr" else 0.0
            ob_cr = ob if ot == "Cr" else 0.0
            opening = round((ob_dr + (ob_txn["dr"] or 0)) - (ob_cr + (ob_txn["cr"] or 0)), 2)

            lines = self.db.execute(
                """SELECT v.voucher_date, v.voucher_number, v.voucher_type,
                          v.narration, v.reference,
                          vl.dr_amount, vl.cr_amount, vl.cleared_date
                   FROM voucher_lines vl
                   JOIN vouchers v ON vl.voucher_id=v.id
                   WHERE vl.ledger_id=? AND v.is_cancelled=0
                     AND v.company_id=? AND v.voucher_date BETWEEN ? AND ?
                   ORDER BY v.voucher_date, v.id""",
                (ldg["id"], self.company_id, from_date, to_date)
            ).fetchall()

            transactions = []
            running = opening
            for line in lines:
                dr = line["dr_amount"] or 0.0
                cr = line["cr_amount"] or 0.0
                running = round(running + dr - cr, 2)
                # Defensive: cleared_date column was added by an additive
                # migration; older rows may not have it on every connection.
                try:
                    cleared = bool(line["cleared_date"])
                except (IndexError, KeyError):
                    cleared = False
                transactions.append({
                    "date":         line["voucher_date"],
                    "voucher_no":   line["voucher_number"],
                    "voucher_type": line["voucher_type"],
                    "narration":    line["narration"] or "",
                    "reference":    line["reference"] or "",
                    "dr":           dr,
                    "cr":           cr,
                    "balance":      running,
                    "cleared":      cleared,
                })
            books.append({
                "ledger":       ldg["name"],
                "opening":      opening,
                "transactions": transactions,
                "closing":      running if transactions else opening,
            })
        return {"books": books, "from_date": from_date, "to_date": to_date}

    # ── 6. Ledger Account ─────────────────────────────────────────────────────

    def ledger_account(self, ledger_id: int, from_date: str, to_date: str) -> dict:
        ldg = self.db.execute(
            """SELECT l.id, l.name, l.opening_balance, l.opening_type,
                      l.is_bank, l.is_cash, l.account_number, l.bank_name,
                      g.name as grp, g.nature as grp_nature
               FROM ledgers l JOIN account_groups g ON l.group_id=g.id
               WHERE l.id=?""",
            (ledger_id,)
        ).fetchone()
        if not ldg:
            return {}
        ob_txn = self.db.execute(
            """SELECT COALESCE(SUM(vl.dr_amount),0) as dr,
                      COALESCE(SUM(vl.cr_amount),0) as cr
               FROM voucher_lines vl
               JOIN vouchers v ON vl.voucher_id=v.id
               WHERE vl.ledger_id=? AND v.is_cancelled=0
                 AND v.company_id=? AND v.voucher_date < ?""",
            (ledger_id, self.company_id, from_date)
        ).fetchone()
        ob = ldg["opening_balance"]
        ot = ldg["opening_type"]
        ob_dr = ob if ot == "Dr" else 0.0
        ob_cr = ob if ot == "Cr" else 0.0
        opening = round((ob_dr + (ob_txn["dr"] or 0)) - (ob_cr + (ob_txn["cr"] or 0)), 2)

        lines = self.db.execute(
            """SELECT v.id as voucher_id,
                      v.voucher_date, v.voucher_number, v.voucher_type,
                      v.narration, v.reference,
                      vl.id as voucher_line_id,
                      vl.dr_amount, vl.cr_amount, vl.line_narration,
                      vl.cleared_date
               FROM voucher_lines vl
               JOIN vouchers v ON vl.voucher_id=v.id
               WHERE vl.ledger_id=? AND v.is_cancelled=0
                 AND v.company_id=? AND v.voucher_date BETWEEN ? AND ?
               ORDER BY v.voucher_date, v.id""",
            (ledger_id, self.company_id, from_date, to_date)
        ).fetchall()

        transactions = []
        running = opening
        for line in lines:
            dr = line["dr_amount"] or 0.0
            cr = line["cr_amount"] or 0.0
            running = round(running + dr - cr, 2)
            try:
                cleared_date = line["cleared_date"] or ""
            except (KeyError, IndexError):
                cleared_date = ""
            transactions.append({
                "voucher_id":      line["voucher_id"],
                "voucher_line_id": line["voucher_line_id"],
                "date":            line["voucher_date"],
                "voucher_no":      line["voucher_number"],
                "type":            line["voucher_type"],
                "narration":       line["line_narration"] or line["narration"] or "",
                "reference":       line["reference"] or "",
                "dr":              dr,
                "cr":              cr,
                "balance":         running,
                "cleared":         bool(cleared_date),
                "cleared_date":    cleared_date,
            })
        return {
            "ledger":         ldg["name"],
            "ledger_id":      ldg["id"],
            "group":          ldg["grp"],
            "group_nature":   ldg["grp_nature"],
            "is_bank":        bool(ldg["is_bank"]),
            "is_cash":        bool(ldg["is_cash"]),
            "account_number": ldg["account_number"],
            "bank_name":      ldg["bank_name"],
            "opening":        opening,
            "transactions":   transactions,
            "closing":        running if transactions else opening,
            "from_date":      from_date,
            "to_date":        to_date,
        }

    # ── 7. Receipts & Payments Summary ────────────────────────────────────────

    def receipts_payments(self, from_date: str, to_date: str) -> dict:
        def get_totals(vtype: str) -> dict:
            row = self.db.execute(
                """SELECT COALESCE(SUM(total_amount),0) as total, COUNT(*) as count
                   FROM vouchers WHERE company_id=? AND voucher_type=?
                     AND is_cancelled=0 AND voucher_date BETWEEN ? AND ?""",
                (self.company_id, vtype, from_date, to_date)
            ).fetchone()
            return {"total": row["total"] or 0.0, "count": row["count"] or 0}

        return {
            "receipts":  get_totals("RECEIPT"),
            "payments":  get_totals("PAYMENT"),
            "sales":     get_totals("SALES"),
            "purchases": get_totals("PURCHASE"),
            "journals":  get_totals("JOURNAL"),
            "contras":   get_totals("CONTRA"),
            "from_date": from_date,
            "to_date":   to_date,
        }

    # ── 8. GST Summary ────────────────────────────────────────────────────────

    def gst_summary(self, from_date: str, to_date: str) -> dict:
        tax_lines = self.db.execute(
            """SELECT vl.tax_type, vl.tax_rate,
                      COALESCE(SUM(vl.cr_amount),0) as output_tax,
                      COALESCE(SUM(vl.dr_amount),0) as input_tax
               FROM voucher_lines vl
               JOIN vouchers v ON vl.voucher_id=v.id
               WHERE v.company_id=? AND v.is_cancelled=0
                 AND vl.is_tax_line=1 AND v.voucher_date BETWEEN ? AND ?
               GROUP BY vl.tax_type, vl.tax_rate
               ORDER BY vl.tax_type, vl.tax_rate""",
            (self.company_id, from_date, to_date)
        ).fetchall()

        sales_base = self.db.execute(
            """SELECT COALESCE(SUM(vl.cr_amount),0) as base
               FROM voucher_lines vl JOIN vouchers v ON vl.voucher_id=v.id
               WHERE v.company_id=? AND v.is_cancelled=0
                 AND v.voucher_type IN ('SALES','CREDIT_NOTE')
                 AND vl.is_tax_line=0 AND v.voucher_date BETWEEN ? AND ?""",
            (self.company_id, from_date, to_date)
        ).fetchone()

        purchase_base = self.db.execute(
            """SELECT COALESCE(SUM(vl.dr_amount),0) as base
               FROM voucher_lines vl JOIN vouchers v ON vl.voucher_id=v.id
               WHERE v.company_id=? AND v.is_cancelled=0
                 AND v.voucher_type IN ('PURCHASE','DEBIT_NOTE')
                 AND vl.is_tax_line=0 AND v.voucher_date BETWEEN ? AND ?""",
            (self.company_id, from_date, to_date)
        ).fetchone()

        rows = [dict(r) for r in tax_lines]
        total_output = sum(r["output_tax"] for r in rows)
        total_input  = sum(r["input_tax"]  for r in rows)
        return {
            "tax_lines":       rows,
            "sales_base":      sales_base["base"]    or 0.0,
            "purchase_base":   purchase_base["base"] or 0.0,
            "total_output":    round(total_output, 2),
            "total_input":     round(total_input,  2),
            "net_gst_payable": round(total_output - total_input, 2),
            "from_date":       from_date,
            "to_date":         to_date,
        }

    # ── 9. TDS Report ─────────────────────────────────────────────────────────

    def tds_report(self, from_date: str, to_date: str) -> dict:
        rows = self.db.execute(
            """SELECT vl.tax_rate,
                      COALESCE(SUM(vl.cr_amount),0) as tds_amount,
                      COUNT(DISTINCT v.id) as voucher_count
               FROM voucher_lines vl
               JOIN vouchers v ON vl.voucher_id=v.id
               WHERE v.company_id=? AND v.is_cancelled=0
                 AND vl.tax_type='TDS' AND v.voucher_date BETWEEN ? AND ?
               GROUP BY vl.tax_rate""",
            (self.company_id, from_date, to_date)
        ).fetchall()
        tds_lines = [dict(r) for r in rows]
        return {
            "tds_lines": tds_lines,
            "total_tds": round(sum(r["tds_amount"] for r in tds_lines), 2),
            "from_date": from_date,
            "to_date":   to_date,
        }

    # ── 10. Day Book ──────────────────────────────────────────────────────────

    def day_book(self, from_date: str, to_date: str,
                 voucher_type: str = None) -> list[dict]:
        q = """SELECT v.voucher_date, v.voucher_number, v.voucher_type,
                      v.narration, v.reference, v.total_amount
               FROM vouchers v
               WHERE v.company_id=? AND v.is_cancelled=0
                 AND v.voucher_date BETWEEN ? AND ?"""
        params: list = [self.company_id, from_date, to_date]
        if voucher_type:
            q += " AND v.voucher_type=?"
            params.append(voucher_type)
        q += " ORDER BY v.voucher_date, v.id"
        return [dict(r) for r in self.db.execute(q, params).fetchall()]
