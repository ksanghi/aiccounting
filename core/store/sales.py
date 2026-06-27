"""
Store HQ — sell & get-paid engine (module #1).

Two sale types, both posting to the shared books via the AccGenie engine:

  • Type-1 COUNTER (anonymous retail): each sale reduces stock + posts COGS
    immediately (real-time on-hand); revenue is posted as ONE daily invoice at
    `close_day` (Dr "Counter Sales" receivable / Cr Sales + Sales Tax). The cash
    portion is received against that bill at once; card/UPI stays outstanding
    until the processor pays out — settled via `receive_payment` (bill-to-bill),
    with the ~2-3% deducted booked as Collection Charges (expense).

  • Type-2 INVOICE (named customer): `create_invoice` posts revenue + COGS
    together (Dr Customer / Cr Sales + Sales Tax), then `receive_payment` settles
    it (full or part) — same bill-wise machinery.

Wraps StoreEngine (re-uses its record_sale for stock+COGS and _ledger for the
accounts joint). No new accounting primitives — just build_sales / build_journal.
"""
from __future__ import annotations

from core.voucher_engine import VoucherLine


class StoreSalesError(Exception):
    pass


def _vno(posted) -> str:
    return getattr(posted, "voucher_number", "") or ""


class StoreSales:
    def __init__(self, store_engine, *, sales_tax_rate: float | None = None):
        self.se = store_engine          # StoreEngine
        self.s = store_engine.s         # StoreDB
        self.eng = store_engine.engine  # accounts VoucherEngine
        self.tree = store_engine.tree   # accounts AccountTree
        self._rate = sales_tax_rate

    # ── helpers ───────────────────────────────────────────────────────────────
    def _tax_rate(self) -> float:
        if self._rate is not None:
            return float(self._rate)
        row = self.tree.db.execute(
            "SELECT sales_tax_rate FROM companies WHERE id=?", (self.tree.company_id,)).fetchone()
        return float((row["sales_tax_rate"] if row else 0) or 0)

    def _group_of_nature(self, nature: str) -> str:
        r = self.tree.db.execute(
            "SELECT name FROM account_groups WHERE company_id=? AND nature=? ORDER BY id LIMIT 1",
            (self.tree.company_id, nature)).fetchone()
        if not r:
            raise StoreSalesError(f"no {nature} group in chart")
        return r["name"]

    def _sales_ledger(self) -> int:
        return self.se._ledger("Sales", self._group_of_nature("INCOME"))

    def _collection_charges(self) -> int:
        return self.se._ledger("Collection Charges", self._group_of_nature("EXPENSE"))

    def _counter_recv(self) -> int:
        return self.se._ledger("Counter Sales", "Sundry Debtors")

    def _next(self, key: str, prefix: str) -> str:
        return f"{prefix}-{self.s.next_number(key):05d}"

    def add_customer(self, name: str, *, contact_person: str = "", phone: str = "",
                     email: str = "", address: str = "", city: str = "", state: str = "",
                     postal_code: str = "", tax_id: str = "", credit_limit: float = 0.0,
                     terms: str = "", notes: str = "") -> int:
        """A named customer IS a Sundry Debtor ledger (per #5), plus a store_customers
        master row holding the contact/credit details. Returns the ledger id."""
        led = self.se._ledger(name, "Sundry Debtors", pan=(tax_id or None))
        row = self.s.execute("SELECT id FROM store_customers WHERE name=?", (name,)).fetchone()
        if not row:
            self.s.execute(
                """INSERT INTO store_customers
                     (name,ledger_id,contact_person,phone,email,address,city,state,
                      postal_code,tax_id,credit_limit,terms,notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name, led, contact_person, phone, email, address, city, state,
                 postal_code, tax_id, float(credit_limit or 0), terms, notes))
            self.s.commit()
        return led

    _CUSTOMER_COLS = ("name", "contact_person", "phone", "email", "address", "city", "state",
                      "postal_code", "tax_id", "credit_limit", "terms", "active", "notes")

    def update_customer(self, customer_id: int, **fields) -> None:
        sets, vals = [], []
        for k, v in fields.items():
            if k not in self._CUSTOMER_COLS:
                raise StoreSalesError(f"unknown customer field: {k}")
            if k == "credit_limit":
                v = float(v or 0)
            elif k == "active":
                v = int(bool(v))
            sets.append(f"{k}=?"); vals.append(v)
        if not sets:
            return
        vals.append(customer_id)
        self.s.execute(f"UPDATE store_customers SET {', '.join(sets)} WHERE id=?", vals)
        self.s.commit()

    # ── Type-1: counter sale (stock+COGS now; revenue at day-close) ───────────
    def record_counter_sale(self, lines, tenders, *, sale_date: str, note: str = "") -> dict:
        """lines: [(item_id, qty, unit_price)] ; tenders: [(tender, amount)]"""
        subtotal = round(sum(float(q) * float(p) for _, q, p in lines), 2)
        rate = self._tax_rate()
        tax = round(subtotal * rate / 100, 2)
        total = round(subtotal + tax, 2)
        sale_no = self._next("SALE", "SALE")
        sid = self.s.execute(
            """INSERT INTO store_sales (sale_no,sale_type,sale_date,subtotal,tax,total)
               VALUES (?,?,?,?,?,?)""",
            (sale_no, "COUNTER", sale_date, subtotal, tax, total)).lastrowid
        for item_id, qty, price in lines:
            self.s.execute(
                "INSERT INTO store_sale_lines (sale_id,item_id,qty,unit_price,line_total) VALUES (?,?,?,?,?)",
                (sid, item_id, float(qty), float(price), round(float(qty) * float(price), 2)))
        for tender, amt in tenders:
            self.s.execute(
                "INSERT INTO store_sale_tenders (sale_id,tender,amount) VALUES (?,?,?)",
                (sid, str(tender).upper(), float(amt)))
        self.s.commit()
        # stock OUT + COGS now → real-time on-hand
        self.se.record_sale([(i, q) for i, q, _ in lines], sale_date=sale_date, ref=sale_no)
        return {"sale_id": sid, "sale_no": sale_no, "subtotal": subtotal, "tax": tax, "total": total}

    def close_day(self, sale_date: str) -> dict:
        """Post ONE daily invoice for the day's open counter sales, and take the
        cash portion in immediately. Card/UPI remain outstanding for payout."""
        rows = self.s.execute(
            "SELECT id, subtotal, tax FROM store_sales WHERE sale_type='COUNTER' AND day_closed=0 AND sale_date=?",
            (sale_date,)).fetchall()
        if not rows:
            raise StoreSalesError(f"no open counter sales on {sale_date}")
        sale_ids = [r["id"] for r in rows]
        subtotal = round(sum(r["subtotal"] for r in rows), 2)
        tax = round(sum(r["tax"] for r in rows), 2)
        total = round(subtotal + tax, 2)
        tot = {"CASH": 0.0, "CARD": 0.0, "UPI": 0.0, "ON_ACCOUNT": 0.0}
        ph = ",".join("?" * len(sale_ids))
        for t in self.s.execute(
                f"SELECT tender, SUM(amount) a FROM store_sale_tenders WHERE sale_id IN ({ph}) GROUP BY tender",
                sale_ids).fetchall():
            tot[t["tender"]] = round(t["a"] or 0.0, 2)

        recv = self._counter_recv()
        day_no = self._next("DAY", "DAY")
        # daily revenue invoice: Dr Counter Sales (gross) / Cr Sales + Sales Tax
        vno = _vno(self.eng.post(self.eng.build_sales(
            voucher_date=sale_date, party_ledger_id=recv, sales_ledger_id=self._sales_ledger(),
            base_amount=subtotal, gst_rate_pct=self._tax_rate(),
            narration=f"Counter sales {sale_date} ({day_no})", reference=day_no)))
        # cash received now → settle the cash slice of the receivable
        if tot["CASH"] > 0:
            self.receive_payment(recv, tot["CASH"], date=sale_date,
                                 to_ledger=("Cash", "Cash-in-Hand", "cash"), ref=day_no)
        self.s.execute(
            """INSERT INTO store_day_close
                 (close_date,voucher_no,cash_total,card_total,upi_total,on_account_total,
                  subtotal,tax,total)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (sale_date, vno, tot["CASH"], tot["CARD"], tot["UPI"], tot["ON_ACCOUNT"],
             subtotal, tax, total))
        self.s.execute(
            f"UPDATE store_sales SET day_closed=1, voucher_no=? WHERE id IN ({ph})", [vno] + sale_ids)
        self.s.commit()
        return {"day_no": day_no, "voucher_no": vno, "subtotal": subtotal, "tax": tax,
                "total": total, "tenders": tot, "outstanding": round(total - tot["CASH"], 2)}

    # ── Type-2: named-customer invoice (revenue + COGS together) ──────────────
    def create_invoice(self, customer_ledger_id: int, lines, *, sale_date: str,
                       customer_id: int | None = None) -> dict:
        subtotal = round(sum(float(q) * float(p) for _, q, p in lines), 2)
        rate = self._tax_rate()
        tax = round(subtotal * rate / 100, 2)
        total = round(subtotal + tax, 2)
        inv_no = self._next("INV", "INV")
        sid = self.s.execute(
            """INSERT INTO store_sales (sale_no,sale_type,customer_id,customer_ledger_id,sale_date,subtotal,tax,total)
               VALUES (?,?,?,?,?,?,?,?)""",
            (inv_no, "INVOICE", customer_id, customer_ledger_id, sale_date, subtotal, tax, total)).lastrowid
        for item_id, qty, price in lines:
            self.s.execute(
                "INSERT INTO store_sale_lines (sale_id,item_id,qty,unit_price,line_total) VALUES (?,?,?,?,?)",
                (sid, item_id, float(qty), float(price), round(float(qty) * float(price), 2)))
        vno = _vno(self.eng.post(self.eng.build_sales(
            voucher_date=sale_date, party_ledger_id=customer_ledger_id, sales_ledger_id=self._sales_ledger(),
            base_amount=subtotal, gst_rate_pct=rate, narration=f"Invoice {inv_no}", reference=inv_no)))
        self.s.execute("UPDATE store_sales SET voucher_no=? WHERE id=?", (vno, sid))
        self.se.record_sale([(i, q) for i, q, _ in lines], sale_date=sale_date, ref=inv_no)
        self.s.commit()
        return {"sale_id": sid, "invoice_no": inv_no, "voucher_no": vno,
                "subtotal": subtotal, "tax": tax, "total": total}

    # ── get paid: bill-wise receipt (full / part), fees → Collection Charges ──
    def receive_payment(self, party_ledger_id: int, amount: float, *, date: str,
                        to_ledger=("Bank Account", "Bank Accounts", "bank"),
                        fees: float = 0.0, ref: str = "") -> str:
        """Dr <bank/cash> (amount) + Dr Collection Charges (fees) / Cr party (amount+fees).
        `to_ledger` = (name, group, 'bank'|'cash'). Use fees for the processor cut on a payout."""
        amount = float(amount); fees = float(fees)
        name, group, kind = to_ledger
        led = self.se._ledger(name, group, **({"is_cash": 1} if kind == "cash" else {"is_bank": 1}))
        lines = [VoucherLine(ledger_id=led, dr_amount=round(amount, 2))]
        if fees > 0:
            lines.append(VoucherLine(ledger_id=self._collection_charges(), dr_amount=round(fees, 2)))
        lines.append(VoucherLine(ledger_id=party_ledger_id, cr_amount=round(amount + fees, 2)))
        return _vno(self.eng.post(self.eng.build_journal(
            voucher_date=date, lines=lines, narration=f"Receipt {ref}".strip(), reference=ref)))

    # ── sale return / credit note (goods back + revenue reversed) ─────────────
    def return_sale(self, lines, *, return_date: str, credit_to, ref: str = "") -> dict:
        """lines: [(item_id, qty, unit_price)] being returned (at sale price).
        credit_to: ('PARTY', customer_ledger_id) to reduce their receivable, OR
                   ('REFUND', (name, group, 'cash'|'bank')) to refund money out."""
        subtotal = round(sum(float(q) * float(p) for _, q, p in lines), 2)
        rate = self._tax_rate()
        tax = round(subtotal * rate / 100, 2)
        total = round(subtotal + tax, 2)
        ret_no = self._next("RET", "RET")
        sid = self.s.execute(
            "INSERT INTO store_sales (sale_no,sale_type,sale_date,subtotal,tax,total) VALUES (?,?,?,?,?,?)",
            (ret_no, "RETURN", return_date, subtotal, tax, total)).lastrowid
        for item_id, qty, price in lines:
            self.s.execute(
                "INSERT INTO store_sale_lines (sale_id,item_id,qty,unit_price,line_total) VALUES (?,?,?,?,?)",
                (sid, item_id, float(qty), float(price), round(float(qty) * float(price), 2)))
        # goods back to stock + reverse COGS
        self.se.return_to_stock([(i, q) for i, q, _ in lines], date=return_date, ref=ret_no)
        # credit note: Dr Sales (+ Dr Sales Tax Payable) / Cr <party or refund>
        vlines = [VoucherLine(ledger_id=self._sales_ledger(), dr_amount=subtotal)]
        if tax > 0:
            vlines.append(VoucherLine(
                ledger_id=self.se._ledger("Sales Tax Payable", "Duties & Taxes"), dr_amount=tax))
        kind, target = credit_to
        if kind == "PARTY":
            cr_led = target
        else:  # REFUND
            name, group, k = target
            cr_led = self.se._ledger(name, group, **({"is_cash": 1} if k == "cash" else {"is_bank": 1}))
        vlines.append(VoucherLine(ledger_id=cr_led, cr_amount=total))
        vno = _vno(self.eng.post(self.eng.build_journal(
            voucher_date=return_date, lines=vlines, narration=f"Sale return {ret_no}", reference=ret_no)))
        self.s.execute("UPDATE store_sales SET voucher_no=? WHERE id=?", (vno, sid))
        self.s.commit()
        return {"return_no": ret_no, "voucher_no": vno, "subtotal": subtotal, "tax": tax, "total": total}

    def counter_receivable_balance(self) -> float:
        """Outstanding on the Counter Sales receivable (card/UPI awaiting payout)."""
        recv = self._counter_recv()
        r = self.tree.db.execute(
            "SELECT COALESCE(SUM(dr_amount),0)-COALESCE(SUM(cr_amount),0) n FROM voucher_lines WHERE ledger_id=?",
            (recv,)).fetchone()
        return round(r["n"] or 0.0, 2)
