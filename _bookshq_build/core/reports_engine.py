"""
Reports Engine — queries DB and returns structured data for all reports.
No UI code here.

FY-awareness (A9): Trial Balance and Balance Sheet are "as on a date"
reports. Real accounts (asset/liability/equity) carry forward
continuously — opening balance + every voucher up to the date. Nominal
accounts (income/expense) must NOT: each financial year stands alone, so
the report shows only the *current* FY's income/expense and folds every
prior FY's net profit into Retained Earnings. The FY boundary comes from
`companies.fy_start`. For a single-FY book the prior-year figures are
all zero, so the output is identical to the pre-A9 behaviour.
"""
from datetime import date, timedelta

from .models import Database
from core.fy import fy_start_year, fy_bounds


class ReportsEngine:

    def __init__(self, db: Database, company_id: int):
        self.db = db
        self.company_id = company_id
        _c = db.connect().execute(
            "SELECT fy_start FROM companies WHERE id=?", (company_id,),
        ).fetchone()
        self.fy_start = (_c["fy_start"] if _c and _c["fy_start"] else "04-01")

    def _fy_open(self, as_of: str) -> str:
        """ISO start date of the financial year that contains `as_of`."""
        sy = fy_start_year(self.fy_start, date.fromisoformat(as_of))
        start, _ = fy_bounds(self.fy_start, sy)
        return start

    def _prior_fy_pnl(self, fy_open: str) -> float:
        """Net profit of every FY *before* the one starting on `fy_open`
        — income (cr−dr) minus expense (dr−cr) for vouchers dated
        strictly before fy_open. Positive = accumulated retained profit."""
        row = self.db.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN g.nature='INCOME'
                              THEN vl.cr_amount - vl.dr_amount ELSE 0 END), 0) AS inc,
                 COALESCE(SUM(CASE WHEN g.nature='EXPENSE'
                              THEN vl.dr_amount - vl.cr_amount ELSE 0 END), 0) AS exp
               FROM voucher_lines vl
               JOIN vouchers v       ON vl.voucher_id = v.id
               JOIN ledgers  l       ON vl.ledger_id  = l.id
               JOIN account_groups g ON l.group_id    = g.id
              WHERE v.company_id = ? AND v.is_cancelled = 0
                AND v.voucher_date < ?""",
            (self.company_id, fy_open),
        ).fetchone()
        return round((row["inc"] or 0.0) - (row["exp"] or 0.0), 2)

    def get_company(self) -> dict:
        row = self.db.execute(
            "SELECT * FROM companies WHERE id=?", (self.company_id,)
        ).fetchone()
        return dict(row) if row else {}

    # ── 1. Trial Balance ──────────────────────────────────────────────────────

    def trial_balance(self, as_of: str) -> list[dict]:
        # Single aggregation query — was N+1 (one query per ledger). On a
        # 115-ledger book this turned every Trial Balance refresh into
        # 116 SQLite round-trips, blocking the UI.
        #
        # `prior_dr` / `prior_cr` capture txns dated BEFORE the current
        # FY opened. For income/expense ledgers we subtract that portion
        # so each ledger shows only the current FY's activity; the
        # removed net becomes a synthetic "Retained Earnings (b/f)" line
        # so the TB still balances.
        fy_open = self._fy_open(as_of)
        cid = self.company_id
        ledger_rows = self.db.execute(
            """SELECT l.id, l.name AS ledger, g.name AS grp, g.nature,
                      l.opening_balance, l.opening_type,
                      COALESCE(SUM(
                        CASE WHEN v.is_cancelled = 0
                              AND v.voucher_date <= ?
                              AND v.company_id = ?
                             THEN vl.dr_amount ELSE 0 END
                      ), 0) AS txn_dr,
                      COALESCE(SUM(
                        CASE WHEN v.is_cancelled = 0
                              AND v.voucher_date <= ?
                              AND v.company_id = ?
                             THEN vl.cr_amount ELSE 0 END
                      ), 0) AS txn_cr,
                      COALESCE(SUM(
                        CASE WHEN v.is_cancelled = 0
                              AND v.voucher_date < ?
                              AND v.company_id = ?
                             THEN vl.dr_amount ELSE 0 END
                      ), 0) AS prior_dr,
                      COALESCE(SUM(
                        CASE WHEN v.is_cancelled = 0
                              AND v.voucher_date < ?
                              AND v.company_id = ?
                             THEN vl.cr_amount ELSE 0 END
                      ), 0) AS prior_cr
                 FROM ledgers l
                 JOIN account_groups g ON l.group_id = g.id
            LEFT JOIN voucher_lines  vl ON vl.ledger_id  = l.id
            LEFT JOIN vouchers       v  ON vl.voucher_id = v.id
                WHERE l.company_id = ? AND l.active = 1
             GROUP BY l.id
             ORDER BY g.nature, g.name, l.name""",
            (as_of, cid, as_of, cid, fy_open, cid, fy_open, cid, cid),
        ).fetchall()

        rows: list[dict] = []
        prior_pnl = 0.0   # net profit of all FYs before the current one
        for l in ledger_rows:
            ob = l["opening_balance"] or 0.0
            ot = l["opening_type"]
            ob_dr  = ob if ot == "Dr" else 0.0
            ob_cr  = ob if ot == "Cr" else 0.0
            txn_dr = l["txn_dr"] or 0.0
            txn_cr = l["txn_cr"] or 0.0

            if l["nature"] in ("INCOME", "EXPENSE"):
                # Strip the pre-FY portion — that profit belongs to a
                # closed year, not this one. (cr−dr) accumulates into
                # prior_pnl: income adds, expense subtracts.
                p_dr = l["prior_dr"] or 0.0
                p_cr = l["prior_cr"] or 0.0
                prior_pnl += (p_cr - p_dr)
                txn_dr -= p_dr
                txn_cr -= p_cr

            net    = (ob_dr + txn_dr) - (ob_cr + txn_cr)
            cl_dr  = round(net, 2)  if net >= 0 else 0.0
            cl_cr  = round(-net, 2) if net  < 0 else 0.0

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

        # Synthetic line carrying prior FYs' accumulated profit. Profit
        # sits as a Cr (retained earnings); a prior loss as a Dr. Without
        # this the TB would be out of balance by exactly the nominal
        # activity we stripped above. Skipped when there is no prior FY.
        prior_pnl = round(prior_pnl, 2)
        if abs(prior_pnl) > 0.001:
            rows.append({
                "ledger":     "Retained Earnings (b/f)",
                "group":      "Reserves & Surplus",
                "nature":     "LIABILITY",
                "opening_dr": 0.0,
                "opening_cr": 0.0,
                "txn_dr":     0.0,
                "txn_cr":     0.0,
                "closing_dr": prior_pnl * -1 if prior_pnl < 0 else 0.0,
                "closing_cr": prior_pnl if prior_pnl > 0 else 0.0,
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

    # ── 2b. US Schedule C (report-only) ───────────────────────────────────────
    # Sole-proprietor profit/loss summary: gross receipts (Part I) and expenses
    # grouped by the ledgers.schedule_c_line tag (Part II). Standard-mileage
    # (miles × rate) lands on line 9 when no actual car expense is tagged. A
    # reporting aid to fill Form 1040 Schedule C — not a filing engine.

    def schedule_c(self, from_date: str, to_date: str,
                   mileage_rate: float | None = None) -> dict:
        from core.schedule_c import (
            SCHEDULE_C_LINES, MileageLog, DEFAULT_MILEAGE_RATE)

        inc = self.db.execute(
            """SELECT COALESCE(SUM(vl.cr_amount),0)
                      - COALESCE(SUM(vl.dr_amount),0) AS amt
                 FROM voucher_lines vl
                 JOIN vouchers v ON vl.voucher_id=v.id
                 JOIN ledgers l ON vl.ledger_id=l.id
                 JOIN account_groups g ON l.group_id=g.id
                WHERE v.company_id=? AND v.is_cancelled=0
                  AND v.voucher_date BETWEEN ? AND ? AND g.nature='INCOME'""",
            (self.company_id, from_date, to_date)
        ).fetchone()
        gross_receipts = round(inc["amt"] or 0.0, 2)

        rows = self.db.execute(
            """SELECT l.schedule_c_line AS code,
                      COALESCE(SUM(vl.dr_amount),0)
                        - COALESCE(SUM(vl.cr_amount),0) AS amt
                 FROM voucher_lines vl
                 JOIN vouchers v ON vl.voucher_id=v.id
                 JOIN ledgers l ON vl.ledger_id=l.id
                 JOIN account_groups g ON l.group_id=g.id
                WHERE v.company_id=? AND v.is_cancelled=0
                  AND v.voucher_date BETWEEN ? AND ? AND g.nature='EXPENSE'
                GROUP BY l.schedule_c_line""",
            (self.company_id, from_date, to_date)
        ).fetchall()
        tagged = {r["code"]: round(r["amt"] or 0.0, 2) for r in rows}
        uncategorised = round(tagged.pop(None, 0.0), 2)  # untagged expense ledgers

        rate = DEFAULT_MILEAGE_RATE if mileage_rate is None else float(mileage_rate)
        miles = MileageLog(self.db, self.company_id).total_miles(from_date, to_date)
        mileage_amount = round(miles * rate, 2)
        # Standard mileage is a tax figure not in the books; fold into line 9 only
        # if the owner hasn't tagged actual car expenses there (avoid double-count).
        if mileage_amount and not tagged.get("car_truck"):
            tagged["car_truck"] = mileage_amount

        lines = []
        for spec in SCHEDULE_C_LINES:
            amt = round(tagged.get(spec["code"], 0.0), 2)
            if amt:
                lines.append({"code": spec["code"], "line": spec["line"],
                              "label": spec["label"], "amount": amt})
        total_expenses = round(sum(l["amount"] for l in lines) + uncategorised, 2)
        return {
            "gross_receipts": gross_receipts,
            "lines":          lines,
            "uncategorised":  uncategorised,
            "total_expenses": total_expenses,
            "net_profit":     round(gross_receipts - total_expenses, 2),
            "mileage":        {"miles": miles, "rate": rate, "amount": mileage_amount},
            "from_date":      from_date,
            "to_date":        to_date,
        }

    # ── 3. Balance Sheet ──────────────────────────────────────────────────────

    def balance_sheet(self, as_of: str) -> dict:
        # Single aggregation per nature — was N+1 (one query per ledger
        # × four natures). On a 115-ledger book that was 115+ round-trips
        # per BS refresh.
        #
        # `from_date` scopes the txn sums to a FY window. Real accounts
        # (asset/liability) pass None → continuous, opening + everything
        # up to `as_of`. Nominal accounts (income/expense) pass the FY
        # open date so the period P&L is the CURRENT year only; prior
        # years' profit is added separately as a Retained Earnings line.
        fy_open = self._fy_open(as_of)

        def get_balances(nature: str, from_date: str | None = None) -> list[dict]:
            lo_clause = "AND v.voucher_date >= ?" if from_date else ""
            params = [as_of, self.company_id]
            if from_date:
                params.append(from_date)
            params += [as_of, self.company_id]
            if from_date:
                params.append(from_date)
            params += [self.company_id, nature]
            rows = self.db.execute(
                f"""SELECT l.id, l.name AS ledger, g.name AS grp,
                          l.opening_balance, l.opening_type,
                          COALESCE(SUM(
                            CASE WHEN v.is_cancelled = 0
                                  AND v.voucher_date <= ?
                                  AND v.company_id = ?
                                  {lo_clause}
                                 THEN vl.dr_amount ELSE 0 END
                          ), 0) AS txn_dr,
                          COALESCE(SUM(
                            CASE WHEN v.is_cancelled = 0
                                  AND v.voucher_date <= ?
                                  AND v.company_id = ?
                                  {lo_clause}
                                 THEN vl.cr_amount ELSE 0 END
                          ), 0) AS txn_cr
                     FROM ledgers l
                     JOIN account_groups g ON l.group_id = g.id
                LEFT JOIN voucher_lines  vl ON vl.ledger_id  = l.id
                LEFT JOIN vouchers       v  ON vl.voucher_id = v.id
                    WHERE l.company_id = ? AND g.nature = ? AND l.active = 1
                 GROUP BY l.id
                 ORDER BY g.name, l.name""",
                params,
            ).fetchall()
            result = []
            for l in rows:
                ob = l["opening_balance"] or 0.0
                ot = l["opening_type"]
                ob_dr = ob if ot == "Dr" else 0.0
                ob_cr = ob if ot == "Cr" else 0.0
                txn_dr = l["txn_dr"] or 0.0
                txn_cr = l["txn_cr"] or 0.0
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

        # Real accounts carry forward continuously; nominal accounts are
        # scoped to the current FY so the period P&L is this year only.
        assets      = get_balances("ASSET")
        liabilities = get_balances("LIABILITY")
        incomes     = get_balances("INCOME",  from_date=fy_open)
        expenses    = get_balances("EXPENSE", from_date=fy_open)

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

        # Net P&L for the period = Income (Cr natural) − Expense (Dr natural).
        # Positive → profit (increases capital); negative → loss (reduces
        # capital). Push it onto the liabilities side as a synthetic
        # "Profit/Loss for the period" row so the BS actually balances —
        # without this, any company with transactions or mid-period opening
        # balances shows an unexplained gap (the user's "Balance Sheet
        # doesn't sum up" complaint).
        total_income  = signed_total(incomes,  "Cr")
        total_expense = signed_total(expenses, "Dr")
        period_pnl    = round(total_income - total_expense, 2)
        if abs(period_pnl) > 0.001:
            liabilities.append({
                "ledger":  "Profit/Loss for the period",
                "group":   "Reserves & Surplus",
                "balance": abs(period_pnl),
                "side":    "Cr" if period_pnl >= 0 else "Dr",
            })

        # Prior FYs' accumulated net profit — retained earnings brought
        # forward. Sits on the liabilities/equity side. Together with the
        # current-FY "Profit/Loss for the period" line above this equals
        # the lifetime profit the pre-A9 single-line version showed, so
        # the sheet still balances. Zero (and omitted) for a single-FY book.
        prior_pnl = self._prior_fy_pnl(fy_open)
        if abs(prior_pnl) > 0.001:
            liabilities.append({
                "ledger":  "Retained Earnings (earlier years)",
                "group":   "Reserves & Surplus",
                "balance": abs(prior_pnl),
                "side":    "Cr" if prior_pnl >= 0 else "Dr",
            })

        return {
            "assets":            assets,
            "liabilities":       liabilities,
            "total_assets":      round(signed_total(assets,      "Dr"), 2),
            "total_liabilities": round(signed_total(liabilities, "Cr"), 2),
            "period_pnl":        period_pnl,
            "prior_pnl":         prior_pnl,
            "total_income":      round(total_income,  2),
            "total_expense":     round(total_expense, 2),
            "as_of":             as_of,
        }

    # ── Receivables aging (A11) ──────────────────────────────────────────────

    def receivables_aging(self, as_of: str) -> dict:
        """Age the outstanding balance of every Sundry Debtor ledger.

        AccGenie is balance-based, not open-item, so aging uses FIFO:
        each debtor's total receipts (Cr) are allocated against its
        charges (Dr) oldest-first; whatever charge amount stays
        unallocated is the outstanding, bucketed by the age of that
        charge (as_of − charge date). A Dr opening balance is treated
        as the oldest charge of all.

        Returns {as_of, rows:[{ledger, b0_30, b31_60, b61_90, b90p,
        total}], totals:{...}}.
        """
        as_of_d = date.fromisoformat(as_of)
        debtor_ledgers = self.db.execute(
            """SELECT l.id, l.name AS ledger,
                      l.opening_balance, l.opening_type
                 FROM ledgers l
                 JOIN account_groups g ON l.group_id = g.id
                WHERE l.company_id = ? AND l.active = 1
                  AND g.name = 'Sundry Debtors'
             ORDER BY l.name""",
            (self.company_id,),
        ).fetchall()

        rows: list[dict] = []
        totals = {"b0_30": 0.0, "b31_60": 0.0, "b61_90": 0.0, "b90p": 0.0}
        for l in debtor_ledgers:
            lines = self.db.execute(
                """SELECT v.voucher_date AS d, vl.dr_amount AS dr,
                          vl.cr_amount AS cr
                     FROM voucher_lines vl
                     JOIN vouchers v ON v.id = vl.voucher_id
                    WHERE vl.ledger_id = ? AND v.is_cancelled = 0
                      AND v.company_id = ? AND v.voucher_date <= ?
                 ORDER BY v.voucher_date, v.id""",
                (l["id"], self.company_id, as_of),
            ).fetchall()

            # Charges = Dr postings oldest-first; a Dr opening balance is
            # the oldest charge (date None). Receipts = all Cr (plus a Cr
            # opening balance).
            charges: list[list] = []
            receipts = 0.0
            ob = l["opening_balance"] or 0.0
            if l["opening_type"] == "Dr" and ob > 0:
                charges.append([None, ob])
            elif l["opening_type"] == "Cr" and ob > 0:
                receipts += ob
            for ln in lines:
                if (ln["dr"] or 0) > 0:
                    charges.append([ln["d"], float(ln["dr"])])
                if (ln["cr"] or 0) > 0:
                    receipts += float(ln["cr"])

            # FIFO — consume oldest charges with the receipt pool.
            pool = receipts
            for ch in charges:
                if pool <= 0:
                    break
                take = min(pool, ch[1])
                ch[1] -= take
                pool  -= take

            lb = {"b0_30": 0.0, "b31_60": 0.0, "b61_90": 0.0, "b90p": 0.0}
            for ch_date, rem in charges:
                if rem <= 0.01:
                    continue
                age = (9999 if ch_date is None
                       else (as_of_d - date.fromisoformat(ch_date)).days)
                if   age <= 30: lb["b0_30"]  += rem
                elif age <= 60: lb["b31_60"] += rem
                elif age <= 90: lb["b61_90"] += rem
                else:           lb["b90p"]   += rem

            total = round(sum(lb.values()), 2)
            if total > 0.01:
                rows.append({
                    "ledger": l["ledger"],
                    "b0_30":  round(lb["b0_30"],  2),
                    "b31_60": round(lb["b31_60"], 2),
                    "b61_90": round(lb["b61_90"], 2),
                    "b90p":   round(lb["b90p"],   2),
                    "total":  total,
                })
                for k in totals:
                    totals[k] += lb[k]

        rows.sort(key=lambda r: r["total"], reverse=True)
        return {
            "as_of":  as_of,
            "rows":   rows,
            "totals": {k: round(v, 2) for k, v in totals.items()},
        }

    def payables_aging(self, as_of: str) -> dict:
        """Age the outstanding balance of every Sundry Creditor ledger — the
        mirror of receivables_aging for what WE owe suppliers.

        FIFO, dr/cr flipped: a creditor's charges are its Cr postings
        (purchases/bills) oldest-first; payments are Dr postings; a Cr opening
        balance is the oldest charge. Returns the same shape as
        receivables_aging.
        """
        as_of_d = date.fromisoformat(as_of)
        creditor_ledgers = self.db.execute(
            """SELECT l.id, l.name AS ledger,
                      l.opening_balance, l.opening_type
                 FROM ledgers l
                 JOIN account_groups g ON l.group_id = g.id
                WHERE l.company_id = ? AND l.active = 1
                  AND g.name = 'Sundry Creditors'
             ORDER BY l.name""",
            (self.company_id,),
        ).fetchall()

        rows: list[dict] = []
        totals = {"b0_30": 0.0, "b31_60": 0.0, "b61_90": 0.0, "b90p": 0.0}
        for l in creditor_ledgers:
            lines = self.db.execute(
                """SELECT v.voucher_date AS d, vl.dr_amount AS dr,
                          vl.cr_amount AS cr
                     FROM voucher_lines vl
                     JOIN vouchers v ON v.id = vl.voucher_id
                    WHERE vl.ledger_id = ? AND v.is_cancelled = 0
                      AND v.company_id = ? AND v.voucher_date <= ?
                 ORDER BY v.voucher_date, v.id""",
                (l["id"], self.company_id, as_of),
            ).fetchall()

            # Charges = what we owe = Cr postings oldest-first (Cr opening =
            # oldest). Payments = Dr postings (+ a Dr opening pool).
            charges: list[list] = []
            payments = 0.0
            ob = l["opening_balance"] or 0.0
            if l["opening_type"] == "Cr" and ob > 0:
                charges.append([None, ob])
            elif l["opening_type"] == "Dr" and ob > 0:
                payments += ob
            for ln in lines:
                if (ln["cr"] or 0) > 0:
                    charges.append([ln["d"], float(ln["cr"])])
                if (ln["dr"] or 0) > 0:
                    payments += float(ln["dr"])

            pool = payments
            for ch in charges:
                if pool <= 0:
                    break
                take = min(pool, ch[1])
                ch[1] -= take
                pool  -= take

            lb = {"b0_30": 0.0, "b31_60": 0.0, "b61_90": 0.0, "b90p": 0.0}
            for ch_date, rem in charges:
                if rem <= 0.01:
                    continue
                age = (9999 if ch_date is None
                       else (as_of_d - date.fromisoformat(ch_date)).days)
                if   age <= 30: lb["b0_30"]  += rem
                elif age <= 60: lb["b31_60"] += rem
                elif age <= 90: lb["b61_90"] += rem
                else:           lb["b90p"]   += rem

            total = round(sum(lb.values()), 2)
            if total > 0.01:
                rows.append({
                    "ledger": l["ledger"],
                    "b0_30":  round(lb["b0_30"],  2),
                    "b31_60": round(lb["b31_60"], 2),
                    "b61_90": round(lb["b61_90"], 2),
                    "b90p":   round(lb["b90p"],   2),
                    "total":  total,
                })
                for k in totals:
                    totals[k] += lb[k]

        rows.sort(key=lambda r: r["total"], reverse=True)
        return {
            "as_of":  as_of,
            "rows":   rows,
            "totals": {k: round(v, 2) for k, v in totals.items()},
        }

    # ── Assisted cash-flow planning (semi-automatic worksheet) ──────────────
    # Posting stays automatic. The user ticks which half-month period they
    # expect each BIG open item to settle (Pareto: only the items that make up
    # ~80% of receipts/payments need a tick — the small 20% tail auto-spreads).
    # The forecast then projects the cash position period-by-period.

    def _opening_cash(self, as_of: str) -> float:
        """Current cash + bank balance as of a date (Dr positive)."""
        row = self.db.execute(
            """SELECT COALESCE(SUM(
                   COALESCE(l.opening_balance,0) *
                     (CASE l.opening_type WHEN 'Dr' THEN 1 ELSE -1 END)
                   + COALESCE(t.net, 0)), 0) AS cash
               FROM ledgers l
               LEFT JOIN (
                   SELECT vl.ledger_id AS lid,
                          SUM(vl.dr_amount - vl.cr_amount) AS net
                     FROM voucher_lines vl
                     JOIN vouchers v ON v.id = vl.voucher_id
                    WHERE v.company_id = ? AND v.is_cancelled = 0
                      AND v.voucher_date <= ?
                    GROUP BY vl.ledger_id
               ) t ON t.lid = l.id
               WHERE l.company_id = ? AND l.active = 1
                 AND (l.is_bank = 1 OR l.is_cash = 1)""",
            (self.company_id, as_of, self.company_id),
        ).fetchone()
        return round((row["cash"] if row else 0.0) or 0.0, 2)

    @staticmethod
    def _pareto(items: list[dict], frac: float = 0.8) -> dict:
        """Split items into the 'vital few' (cumulative >= frac of total, biggest
        first) + the small tail amount. items: [{ledger_id, party, amount}]."""
        items = sorted(items, key=lambda x: x["amount"], reverse=True)
        total = round(sum(i["amount"] for i in items), 2)
        vital, acc = [], 0.0
        for it in items:
            vital.append(it)
            acc += it["amount"]
            if total <= 0 or acc >= frac * total - 0.01:
                break
        return {"vital": vital, "tail": round(total - acc, 2), "total": total}

    def cashflow_open_items(self, as_of: str) -> dict:
        """Open receivables (IN) + payables (OUT) by party, Pareto-split."""
        rows = self.db.execute(
            """SELECT l.id, l.name, g.name AS grp, l.opening_balance,
                      l.opening_type,
                      COALESCE(SUM(CASE WHEN v.id IS NOT NULL
                                   THEN vl.dr_amount - vl.cr_amount ELSE 0 END), 0) AS moved
                 FROM ledgers l
                 JOIN account_groups g ON l.group_id = g.id
                 LEFT JOIN voucher_lines vl ON vl.ledger_id = l.id
                 LEFT JOIN vouchers v ON v.id = vl.voucher_id
                      AND v.is_cancelled = 0 AND v.voucher_date <= ?
                WHERE l.company_id = ? AND l.active = 1
                  AND g.name IN ('Sundry Debtors', 'Sundry Creditors')
                GROUP BY l.id""",
            (as_of, self.company_id),
        ).fetchall()
        inc, out = [], []
        for r in rows:
            ob = (r["opening_balance"] or 0.0) * (1 if r["opening_type"] == "Dr" else -1)
            net = round(ob + (r["moved"] or 0.0), 2)
            if r["grp"] == "Sundry Debtors" and net > 0.01:
                inc.append({"ledger_id": r["id"], "party": r["name"], "amount": net})
            elif r["grp"] == "Sundry Creditors" and net < -0.01:
                out.append({"ledger_id": r["id"], "party": r["name"], "amount": round(-net, 2)})
        return {"in": self._pareto(inc), "out": self._pareto(out)}

    def cashflow_periods(self, as_of: str, months: int = 4) -> list[dict]:
        """Upcoming half-month periods (1–15, 16–end) for `months` months."""
        d0 = date.fromisoformat(as_of)
        periods = []
        for k in range(months):
            mm = d0.month + k
            yy = d0.year + (mm - 1) // 12
            mm = (mm - 1) % 12 + 1
            nextm = date(yy + 1, 1, 1) if mm == 12 else date(yy, mm + 1, 1)
            halves = [(date(yy, mm, 1), date(yy, mm, 15)),
                      (date(yy, mm, 16), nextm - timedelta(days=1))]
            for s, e in halves:
                if e >= d0:
                    periods.append({
                        "start": s.isoformat(), "end": e.isoformat(),
                        "label": f"{s.day}–{e.day} {s.strftime('%b %y')}",
                    })
        return periods

    def cashflow_get_expectations(self) -> dict:
        rows = self.db.execute(
            "SELECT ledger_id, kind, period_start FROM cashflow_expectations "
            "WHERE company_id = ?", (self.company_id,),
        ).fetchall()
        return {(r["ledger_id"], r["kind"]): r["period_start"] for r in rows}

    def cashflow_set_expectation(self, ledger_id: int, kind: str,
                                 period_start: str | None) -> None:
        if not period_start:
            self.db.execute(
                "DELETE FROM cashflow_expectations "
                "WHERE company_id=? AND ledger_id=? AND kind=?",
                (self.company_id, ledger_id, kind))
        else:
            self.db.execute(
                """INSERT INTO cashflow_expectations
                   (company_id, ledger_id, kind, period_start)
                   VALUES (?,?,?,?)
                   ON CONFLICT(company_id, ledger_id, kind)
                   DO UPDATE SET period_start = excluded.period_start,
                                 updated_at = datetime('now')""",
                (self.company_id, ledger_id, kind, period_start))
        self.db.commit()

    def cashflow_forecast(self, as_of: str, months: int = 4) -> dict:
        """Project the cash position period-by-period from the user's expected
        periods. Vital-few items land in their ticked period (or 'unscheduled'
        until ticked); the small ~20% tail spreads evenly across the horizon."""
        opening = self._opening_cash(as_of)
        items = self.cashflow_open_items(as_of)
        periods = self.cashflow_periods(as_of, months)
        exp = self.cashflow_get_expectations()

        pmap = {p["start"]: {"label": p["label"], "in": 0.0, "out": 0.0}
                for p in periods}
        order = [p["start"] for p in periods]
        unsched_in = unsched_out = 0.0
        for it in items["in"]["vital"]:
            ps = exp.get((it["ledger_id"], "IN"))
            if ps in pmap:
                pmap[ps]["in"] += it["amount"]
            else:
                unsched_in += it["amount"]
        for it in items["out"]["vital"]:
            ps = exp.get((it["ledger_id"], "OUT"))
            if ps in pmap:
                pmap[ps]["out"] += it["amount"]
            else:
                unsched_out += it["amount"]

        n = len(order) or 1
        tail_in = items["in"]["tail"] / n
        tail_out = items["out"]["tail"] / n

        rows, closing = [], opening
        for ps in order:
            b = pmap[ps]
            inflow = round(b["in"] + tail_in, 2)
            outflow = round(b["out"] + tail_out, 2)
            net = round(inflow - outflow, 2)
            closing = round(closing + net, 2)
            rows.append({"label": b["label"], "inflow": inflow,
                         "outflow": outflow, "net": net, "closing": closing})
        return {
            "as_of": as_of, "opening": opening, "rows": rows,
            "unscheduled_in": round(unsched_in, 2),
            "unscheduled_out": round(unsched_out, 2),
            "tail_in": items["in"]["tail"], "tail_out": items["out"]["tail"],
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
                """SELECT v.id AS voucher_id,
                          v.voucher_date, v.voucher_number, v.voucher_type,
                          v.narration, v.reference,
                          vl.dr_amount, vl.cr_amount, vl.cleared_date,
                          (SELECT l2.name
                             FROM voucher_lines vl2
                             JOIN ledgers l2 ON l2.id = vl2.ledger_id
                            WHERE vl2.voucher_id = v.id
                              AND vl2.ledger_id != vl.ledger_id
                            ORDER BY (vl2.dr_amount + vl2.cr_amount) DESC
                            LIMIT 1) AS party,
                          (SELECT COUNT(*) FROM voucher_lines vl3
                            WHERE vl3.voucher_id = v.id
                              AND vl3.ledger_id != vl.ledger_id) AS contra_n
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
                party = line["party"] or ""
                if party and (line["contra_n"] or 0) > 1:
                    party = f"{party}  (+{line['contra_n'] - 1})"
                transactions.append({
                    "voucher_id":   line["voucher_id"],
                    "date":         line["voucher_date"],
                    "voucher_no":   line["voucher_number"],
                    "voucher_type": line["voucher_type"],
                    "party":        party,
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
                      vl.cleared_date,
                      (SELECT l2.name
                         FROM voucher_lines vl2
                         JOIN ledgers l2 ON l2.id = vl2.ledger_id
                        WHERE vl2.voucher_id = v.id
                          AND vl2.ledger_id != vl.ledger_id
                        ORDER BY (vl2.dr_amount + vl2.cr_amount) DESC
                        LIMIT 1) AS party,
                      (SELECT COUNT(*) FROM voucher_lines vl3
                        WHERE vl3.voucher_id = v.id
                          AND vl3.ledger_id != vl.ledger_id) AS contra_n
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
            party = line["party"] or ""
            if party and (line["contra_n"] or 0) > 1:
                party = f"{party}  (+{line['contra_n'] - 1})"
            transactions.append({
                "voucher_id":      line["voucher_id"],
                "voucher_line_id": line["voucher_line_id"],
                "date":            line["voucher_date"],
                "voucher_no":      line["voucher_number"],
                "type":            line["voucher_type"],
                "party":           party,
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

    # ── 9b. US Form 1099 (report-only) ────────────────────────────────────────
    # No withholding — sums gross amounts PAID (cash basis, PAYMENT vouchers) to
    # each ledger flagged is_tds_applicable=1 (the 1099-reportable marker) in the
    # period. Contractors paid >= threshold are 1099-NEC reportable.

    def form_1099(self, from_date: str, to_date: str,
                  threshold: float = 600.0) -> dict:
        rows = self.db.execute(
            """SELECT l.id, l.name, l.tds_section AS form_type,
                      COALESCE(SUM(vl.dr_amount),0)
                        - COALESCE(SUM(vl.cr_amount),0) AS paid
                 FROM ledgers l
                 JOIN voucher_lines vl ON vl.ledger_id = l.id
                 JOIN vouchers v ON vl.voucher_id = v.id
                WHERE l.company_id=? AND l.is_tds_applicable=1
                  AND v.is_cancelled=0 AND v.voucher_type='PAYMENT'
                  AND v.voucher_date BETWEEN ? AND ?
                GROUP BY l.id, l.name, l.tds_section
                HAVING paid > 0
                ORDER BY paid DESC""",
            (self.company_id, from_date, to_date)
        ).fetchall()
        contractors = [
            {
                "ledger_id":  r["id"],
                "name":       r["name"],
                "form_type":  r["form_type"] or "1099-NEC",
                "total_paid": round(r["paid"], 2),
                "reportable": round(r["paid"], 2) >= threshold,
            }
            for r in rows
        ]
        return {
            "contractors":      contractors,
            "total_paid":       round(sum(c["total_paid"] for c in contractors), 2),
            "reportable_count": sum(1 for c in contractors if c["reportable"]),
            "threshold":        threshold,
            "from_date":        from_date,
            "to_date":          to_date,
        }

    # ── 8b. GSTR-3B working ───────────────────────────────────────────────────
    # me-too summary return: outward tax liability vs eligible ITC -> net
    # payable. Built from posted tax lines (NOT filing — that's compliance).
    # Outward = SALES less CREDIT_NOTE; inward ITC = PURCHASE less DEBIT_NOTE.

    _GST_TYPES = ("IGST", "CGST", "SGST")

    def _gst_tax_by_type(self, vtypes, col, from_date, to_date) -> dict:
        ph = ",".join("?" * len(vtypes))
        rows = self.db.execute(
            f"""SELECT vl.tax_type, COALESCE(SUM(vl.{col}),0) AS amt
                  FROM voucher_lines vl JOIN vouchers v ON vl.voucher_id=v.id
                 WHERE v.company_id=? AND v.is_cancelled=0 AND vl.is_tax_line=1
                   AND vl.tax_type IN ('CGST','SGST','IGST')
                   AND v.voucher_type IN ({ph})
                   AND v.voucher_date BETWEEN ? AND ?
                 GROUP BY vl.tax_type""",
            (self.company_id, *vtypes, from_date, to_date),
        ).fetchall()
        return {r["tax_type"]: (r["amt"] or 0.0) for r in rows}

    def _gst_base(self, vtypes, col, from_date, to_date) -> float:
        ph = ",".join("?" * len(vtypes))
        row = self.db.execute(
            f"""SELECT COALESCE(SUM(vl.{col}),0) AS base
                  FROM voucher_lines vl JOIN vouchers v ON vl.voucher_id=v.id
                  JOIN ledgers l ON vl.ledger_id=l.id
                  JOIN account_groups g ON l.group_id=g.id
                 WHERE v.company_id=? AND v.is_cancelled=0 AND vl.is_tax_line=0
                   AND g.nature='INCOME' AND v.voucher_type IN ({ph})
                   AND v.voucher_date BETWEEN ? AND ?""",
            (self.company_id, *vtypes, from_date, to_date),
        ).fetchone()
        return row["base"] or 0.0

    def gstr3b(self, from_date: str, to_date: str) -> dict:
        out_s = self._gst_tax_by_type(["SALES"], "cr_amount", from_date, to_date)
        out_cn = self._gst_tax_by_type(["CREDIT_NOTE"], "cr_amount", from_date, to_date)
        in_p = self._gst_tax_by_type(["PURCHASE"], "dr_amount", from_date, to_date)
        in_dn = self._gst_tax_by_type(["DEBIT_NOTE"], "dr_amount", from_date, to_date)

        outward = {t: round(out_s.get(t, 0.0) - out_cn.get(t, 0.0), 2) for t in self._GST_TYPES}
        itc = {t: round(in_p.get(t, 0.0) - in_dn.get(t, 0.0), 2) for t in self._GST_TYPES}
        net = {t: round(outward[t] - itc[t], 2) for t in self._GST_TYPES}

        taxable = round(self._gst_base(["SALES"], "cr_amount", from_date, to_date)
                        - self._gst_base(["CREDIT_NOTE"], "cr_amount", from_date, to_date), 2)
        return {
            "outward":       {"taxable": taxable, **outward},
            "itc":           itc,
            "net_payable":   net,
            "total_output":  round(sum(outward.values()), 2),
            "total_itc":     round(sum(itc.values()), 2),
            "total_payable": round(sum(net.values()), 2),
            "from_date":     from_date,
            "to_date":       to_date,
        }

    # ── 8c. GSTR-1 (outward supplies, invoice/party-wise) ─────────────────────
    # me-too sales return: one row per invoice, B2B (party has GSTIN) vs B2C,
    # with CGST/SGST/IGST. CREDIT_NOTE rows are signed negative. HSN summary is
    # a follow-up (needs an hsn column at entry — schema touch).

    def gstr1(self, from_date: str, to_date: str) -> dict:
        rows = self.db.execute(
            """SELECT v.id, v.voucher_number AS invoice_no, v.voucher_date AS invoice_date,
                      v.voucher_type AS doc_type,
                      (SELECT l.name FROM voucher_lines x JOIN ledgers l ON x.ledger_id=l.id
                         JOIN account_groups g ON l.group_id=g.id
                        WHERE x.voucher_id=v.id AND g.name='Sundry Debtors'
                        ORDER BY x.dr_amount DESC LIMIT 1) AS party,
                      (SELECT l.gstin FROM voucher_lines x JOIN ledgers l ON x.ledger_id=l.id
                         JOIN account_groups g ON l.group_id=g.id
                        WHERE x.voucher_id=v.id AND g.name='Sundry Debtors'
                        ORDER BY x.dr_amount DESC LIMIT 1) AS gstin,
                      (SELECT l.state_code FROM voucher_lines x JOIN ledgers l ON x.ledger_id=l.id
                         JOIN account_groups g ON l.group_id=g.id
                        WHERE x.voucher_id=v.id AND g.name='Sundry Debtors'
                        ORDER BY x.dr_amount DESC LIMIT 1) AS pos,
                      COALESCE((SELECT SUM(x.cr_amount) FROM voucher_lines x
                         JOIN ledgers l ON x.ledger_id=l.id JOIN account_groups g ON l.group_id=g.id
                        WHERE x.voucher_id=v.id AND x.is_tax_line=0 AND g.nature='INCOME'),0) AS taxable,
                      COALESCE((SELECT SUM(cr_amount) FROM voucher_lines WHERE voucher_id=v.id AND tax_type='CGST'),0) AS cgst,
                      COALESCE((SELECT SUM(cr_amount) FROM voucher_lines WHERE voucher_id=v.id AND tax_type='SGST'),0) AS sgst,
                      COALESCE((SELECT SUM(cr_amount) FROM voucher_lines WHERE voucher_id=v.id AND tax_type='IGST'),0) AS igst
                 FROM vouchers v
                WHERE v.company_id=? AND v.is_cancelled=0
                  AND v.voucher_type IN ('SALES','CREDIT_NOTE')
                  AND v.voucher_date BETWEEN ? AND ?
                ORDER BY v.voucher_date, v.id""",
            (self.company_id, from_date, to_date),
        ).fetchall()

        invoices, b2b, b2c = [], {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "count": 0}, \
            {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "count": 0}
        for r in rows:
            sign = -1.0 if r["doc_type"] == "CREDIT_NOTE" else 1.0
            inv = {
                "invoice_no": r["invoice_no"], "invoice_date": r["invoice_date"],
                "doc_type": r["doc_type"], "party": r["party"] or "(cash / unregistered)",
                "gstin": r["gstin"] or "", "pos": r["pos"] or "",
                "taxable": round(sign * (r["taxable"] or 0.0), 2),
                "cgst": round(sign * (r["cgst"] or 0.0), 2),
                "sgst": round(sign * (r["sgst"] or 0.0), 2),
                "igst": round(sign * (r["igst"] or 0.0), 2),
                "category": "B2B" if r["gstin"] else "B2C",
            }
            invoices.append(inv)
            bucket = b2b if r["gstin"] else b2c
            for k in ("taxable", "cgst", "sgst", "igst"):
                bucket[k] = round(bucket[k] + inv[k], 2)
            bucket["count"] += 1
        return {
            "invoices": invoices, "b2b": b2b, "b2c": b2c,
            "total_taxable": round(b2b["taxable"] + b2c["taxable"], 2),
            "total_tax": round(sum(b2b[k] + b2c[k] for k in ("cgst", "sgst", "igst")), 2),
            "from_date": from_date, "to_date": to_date,
        }

    # ── 8d. GSTR-2B reconciliation (ITC matching) ─────────────────────────────
    # Match the portal's 2B (what suppliers reported) against our purchase/ITC
    # records. Import-and-match like bank reco — NO GSP, NO filing. The marquee
    # PRO feature: catches ITC at risk (supplier didn't report a bill).

    def _purchase_invoices(self, from_date: str, to_date: str) -> list[dict]:
        rows = self.db.execute(
            """SELECT v.id, v.reference AS invoice_no, v.voucher_date AS invoice_date,
                      (SELECT l.name FROM voucher_lines x JOIN ledgers l ON x.ledger_id=l.id
                         JOIN account_groups g ON l.group_id=g.id
                        WHERE x.voucher_id=v.id AND g.name='Sundry Creditors'
                        ORDER BY x.cr_amount DESC LIMIT 1) AS party,
                      (SELECT l.gstin FROM voucher_lines x JOIN ledgers l ON x.ledger_id=l.id
                         JOIN account_groups g ON l.group_id=g.id
                        WHERE x.voucher_id=v.id AND g.name='Sundry Creditors'
                        ORDER BY x.cr_amount DESC LIMIT 1) AS gstin,
                      COALESCE((SELECT SUM(x.dr_amount) FROM voucher_lines x
                         JOIN ledgers l ON x.ledger_id=l.id JOIN account_groups g ON l.group_id=g.id
                        WHERE x.voucher_id=v.id AND x.is_tax_line=0 AND g.nature='EXPENSE'),0) AS taxable,
                      COALESCE((SELECT SUM(dr_amount) FROM voucher_lines WHERE voucher_id=v.id AND tax_type='CGST'),0) AS cgst,
                      COALESCE((SELECT SUM(dr_amount) FROM voucher_lines WHERE voucher_id=v.id AND tax_type='SGST'),0) AS sgst,
                      COALESCE((SELECT SUM(dr_amount) FROM voucher_lines WHERE voucher_id=v.id AND tax_type='IGST'),0) AS igst
                 FROM vouchers v
                WHERE v.company_id=? AND v.is_cancelled=0
                  AND v.voucher_type IN ('PURCHASE','DEBIT_NOTE')
                  AND v.voucher_date BETWEEN ? AND ?
                ORDER BY v.voucher_date, v.id""",
            (self.company_id, from_date, to_date),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _inv_key(gstin, inv):
        return ((gstin or "").strip().upper(), "".join((inv or "").split()).upper())

    def gstr2b_reconcile(self, from_date: str, to_date: str, portal_rows: list) -> dict:
        books = self._purchase_invoices(from_date, to_date)
        book_idx: dict = {}
        for b in books:
            book_idx.setdefault(self._inv_key(b["gstin"], b["invoice_no"]), []).append(b)

        matched, mismatch, only_books, only_2b = [], [], [], []
        consumed = set()
        for p in portal_rows:
            cands = book_idx.get(self._inv_key(p["gstin"], p["invoice_no"]))
            if cands:
                b = cands.pop(0)
                consumed.add(id(b))
                p_tax = round(p["igst"] + p["cgst"] + p["sgst"], 2)
                b_tax = round((b["igst"] or 0) + (b["cgst"] or 0) + (b["sgst"] or 0), 2)
                rec = {
                    "gstin": p["gstin"], "invoice_no": p["invoice_no"], "party": b["party"] or "",
                    "book_taxable": round(b["taxable"] or 0, 2), "b2b_taxable": p["taxable"],
                    "book_tax": b_tax, "b2b_tax": p_tax, "diff": round(b_tax - p_tax, 2),
                }
                ok = abs(b_tax - p_tax) <= 1.0 and abs((b["taxable"] or 0) - p["taxable"]) <= 1.0
                (matched if ok else mismatch).append(rec)
            else:
                only_2b.append({
                    "gstin": p["gstin"], "invoice_no": p["invoice_no"], "party": "",
                    "b2b_taxable": p["taxable"], "b2b_tax": round(p["igst"] + p["cgst"] + p["sgst"], 2),
                })
        for b in books:
            if id(b) not in consumed:
                only_books.append({
                    "gstin": b["gstin"] or "", "invoice_no": b["invoice_no"] or "", "party": b["party"] or "",
                    "book_taxable": round(b["taxable"] or 0, 2),
                    "book_tax": round((b["igst"] or 0) + (b["cgst"] or 0) + (b["sgst"] or 0), 2),
                })
        return {
            "matched": matched, "mismatch": mismatch,
            "only_books": only_books, "only_2b": only_2b,
            "n_matched": len(matched), "n_mismatch": len(mismatch),
            "n_only_books": len(only_books), "n_only_2b": len(only_2b),
            "itc_matched": round(sum(r["book_tax"] for r in matched), 2),
            "itc_at_risk": round(sum(r["book_tax"] for r in only_books), 2),
            "from_date": from_date, "to_date": to_date,
        }

    # ── 9b. TDS Register (26Q-style, by deductee party + section) ─────────────
    # Deductee = the party line (ledger with is_tds_applicable=1) on a voucher
    # that carries a TDS tax line; gross = amount paid to that party; tds = the
    # TDS line. Aggregated by (party, section) with PAN — the 26Q working set.

    def tds_register(self, from_date: str, to_date: str) -> dict:
        rows = self.db.execute(
            """SELECT
                  (SELECT l.name FROM voucher_lines x JOIN ledgers l ON x.ledger_id=l.id
                     WHERE x.voucher_id=v.id AND l.is_tds_applicable=1 AND x.is_tax_line=0
                     ORDER BY x.dr_amount DESC LIMIT 1) AS party,
                  (SELECT l.pan FROM voucher_lines x JOIN ledgers l ON x.ledger_id=l.id
                     WHERE x.voucher_id=v.id AND l.is_tds_applicable=1 AND x.is_tax_line=0
                     ORDER BY x.dr_amount DESC LIMIT 1) AS pan,
                  (SELECT l.tds_section FROM voucher_lines x JOIN ledgers l ON x.ledger_id=l.id
                     WHERE x.voucher_id=v.id AND l.is_tds_applicable=1 AND x.is_tax_line=0
                     ORDER BY x.dr_amount DESC LIMIT 1) AS section,
                  COALESCE((SELECT SUM(x.dr_amount) FROM voucher_lines x JOIN ledgers l ON x.ledger_id=l.id
                     WHERE x.voucher_id=v.id AND l.is_tds_applicable=1 AND x.is_tax_line=0),0) AS gross,
                  COALESCE((SELECT SUM(cr_amount) FROM voucher_lines WHERE voucher_id=v.id AND tax_type='TDS'),0) AS tds,
                  COALESCE((SELECT MAX(tax_rate) FROM voucher_lines WHERE voucher_id=v.id AND tax_type='TDS'),0) AS rate
                 FROM vouchers v
                WHERE v.company_id=? AND v.is_cancelled=0
                  AND v.voucher_date BETWEEN ? AND ?
                  AND EXISTS (SELECT 1 FROM voucher_lines WHERE voucher_id=v.id AND tax_type='TDS')
                ORDER BY v.voucher_date, v.id""",
            (self.company_id, from_date, to_date),
        ).fetchall()

        try:
            from core.voucher_engine import TDS_SECTIONS
        except Exception:
            TDS_SECTIONS = {}

        agg: dict = {}
        for r in rows:
            key = (r["party"] or "(unknown)", r["section"] or "")
            a = agg.setdefault(key, {
                "party": r["party"] or "(unknown)", "pan": r["pan"] or "",
                "section": r["section"] or "", "rate": r["rate"] or 0.0,
                "gross": 0.0, "tds": 0.0, "count": 0,
            })
            a["gross"] = round(a["gross"] + (r["gross"] or 0), 2)
            a["tds"] = round(a["tds"] + (r["tds"] or 0), 2)
            a["count"] += 1
        parties = sorted(agg.values(), key=lambda x: (x["section"], x["party"]))
        for p in parties:
            p["section_desc"] = (TDS_SECTIONS.get(p["section"], {}) or {}).get("desc", "")
        return {
            "parties":     parties,
            "total_gross": round(sum(p["gross"] for p in parties), 2),
            "total_tds":   round(sum(p["tds"] for p in parties), 2),
            "from_date":   from_date, "to_date": to_date,
        }

    # ── 8e. HSN summary (GSTR-1 outward, by HSN/SAC) ──────────────────────────
    # Group outward supplies by the income ledger's hsn_code. Voucher tax
    # (CGST/SGST/IGST) is allocated to each income line proportionally by its
    # taxable share, so multi-HSN invoices split correctly. CREDIT_NOTE signed
    # negative. Ledgers with no HSN fall under "(no HSN)".

    def hsn_summary(self, from_date: str, to_date: str) -> dict:
        inc = self.db.execute(
            """SELECT v.id AS vid, v.voucher_type AS vt,
                      COALESCE(l.hsn_code,'') AS hsn, vl.cr_amount AS taxable
                 FROM voucher_lines vl JOIN vouchers v ON vl.voucher_id=v.id
                 JOIN ledgers l ON vl.ledger_id=l.id
                 JOIN account_groups g ON l.group_id=g.id
                WHERE v.company_id=? AND v.is_cancelled=0 AND vl.is_tax_line=0
                  AND g.nature='INCOME' AND v.voucher_type IN ('SALES','CREDIT_NOTE')
                  AND v.voucher_date BETWEEN ? AND ?""",
            (self.company_id, from_date, to_date),
        ).fetchall()
        tax = self.db.execute(
            """SELECT v.id AS vid, vl.tax_type AS tt, COALESCE(SUM(vl.cr_amount),0) AS amt
                 FROM voucher_lines vl JOIN vouchers v ON vl.voucher_id=v.id
                WHERE v.company_id=? AND v.is_cancelled=0 AND vl.is_tax_line=1
                  AND vl.tax_type IN ('CGST','SGST','IGST')
                  AND v.voucher_type IN ('SALES','CREDIT_NOTE')
                  AND v.voucher_date BETWEEN ? AND ?
                GROUP BY v.id, vl.tax_type""",
            (self.company_id, from_date, to_date),
        ).fetchall()

        vtax: dict = {}
        for r in tax:
            vtax.setdefault(r["vid"], {"CGST": 0.0, "SGST": 0.0, "IGST": 0.0})[r["tt"]] = r["amt"] or 0.0
        vinc: dict = {}
        vtype: dict = {}
        for r in inc:
            vinc.setdefault(r["vid"], []).append((r["hsn"] or "(no HSN)", r["taxable"] or 0.0))
            vtype[r["vid"]] = r["vt"]

        agg: dict = {}
        for vid, lines in vinc.items():
            sign = -1.0 if vtype[vid] == "CREDIT_NOTE" else 1.0
            total = sum(t for _, t in lines)
            vt = vtax.get(vid, {"CGST": 0.0, "SGST": 0.0, "IGST": 0.0})
            for hsn, taxable in lines:
                share = (taxable / total) if total else 0.0
                a = agg.setdefault(hsn, {"hsn": hsn, "taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0})
                a["taxable"] += sign * taxable
                a["cgst"] += sign * vt["CGST"] * share
                a["sgst"] += sign * vt["SGST"] * share
                a["igst"] += sign * vt["IGST"] * share

        rows = []
        for hsn in sorted(agg):
            a = agg[hsn]
            rows.append({k: (round(v, 2) if isinstance(v, float) else v) for k, v in a.items()})
        return {
            "rows":          rows,
            "total_taxable": round(sum(r["taxable"] for r in rows), 2),
            "total_tax":     round(sum(r["cgst"] + r["sgst"] + r["igst"] for r in rows), 2),
            "from_date":     from_date, "to_date": to_date,
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
