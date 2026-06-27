"""
Store HQ engine — inventory + purchasing, posting to the shared accounts books.

The store data lives in its own DB (StoreDB). The accounts side is reached only
through the AccGenie VoucherEngine + AccountTree passed in; the engine resolves
(or creates) the Stock-in-Trade / COGS / supplier ledgers and posts vouchers,
storing the returned voucher number on store rows as the audit link. No
cross-database foreign keys — this is the module-data-boundary in practice.

Inventory method: perpetual weighted-average cost, recomputed by replaying the
store_stock_movements ledger (positive = IN, negative = OUT).
"""
from __future__ import annotations

from core.voucher_engine import VoucherLine


class StoreError(Exception):
    pass


class StoreEngine:
    def __init__(self, store_db, engine, tree, *, default_tax_rate: float = 0.0):
        self.s = store_db          # StoreDB (own file)
        self.engine = engine       # accounts VoucherEngine
        self.tree = tree           # accounts AccountTree
        self.tax = float(default_tax_rate)

    # ── accounts ledgers (the joint to the books) ─────────────────────────────
    def _ledger(self, name: str, group_name: str, **kw) -> int:
        row = self.tree.db.execute(
            "SELECT id FROM ledgers WHERE company_id=? AND name=?",
            (self.tree.company_id, name)).fetchone()
        if row:
            return row["id"]
        return self.tree.add_ledger(name=name, group_name=group_name, **kw)

    def _inventory_ledger(self) -> int: return self._ledger("Inventory", "Stock-in-Trade")
    def _cogs_ledger(self) -> int:      return self._ledger("Cost of Goods Sold", "Purchase Accounts")
    def _shrinkage_ledger(self) -> int: return self._ledger("Inventory Shrinkage", "Indirect Expenses")

    @staticmethod
    def _vno(posted) -> str:
        return getattr(posted, "voucher_number", "") or ""

    # ── catalog ───────────────────────────────────────────────────────────────
    def _category_id(self, name: str | None):
        name = (name or "").strip()
        if not name:
            return None
        r = self.s.execute("SELECT id FROM store_categories WHERE name=?", (name,)).fetchone()
        if r:
            return r["id"]
        cur = self.s.execute("INSERT INTO store_categories (name) VALUES (?)", (name,))
        self.s.commit()
        return cur.lastrowid

    def add_item(self, sku: str, name: str, *, description: str = "", category: str = "",
                 brand: str = "", unit: str = "pc", purchase_unit: str = "",
                 units_per_purchase: float = 1, sale_price: float = 0.0, mrp: float = 0.0,
                 min_price: float = 0.0, taxable: bool = True, tax_code: str = "",
                 reorder_level: float = 0.0, reorder_qty: float = 0.0, max_level: float = 0.0,
                 preferred_supplier_id: int | None = None, barcode: str = "") -> int:
        cur = self.s.execute(
            """INSERT INTO store_items
                 (sku,barcode,name,description,category_id,brand,unit,purchase_unit,
                  units_per_purchase,sale_price,mrp,min_price,taxable,tax_code,
                  reorder_level,reorder_qty,max_level,preferred_supplier_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sku, barcode, name, description, self._category_id(category), brand, unit,
             purchase_unit, float(units_per_purchase or 1), float(sale_price), float(mrp),
             float(min_price), int(bool(taxable)), tax_code, float(reorder_level),
             float(reorder_qty), float(max_level), preferred_supplier_id))
        self.s.commit()
        return cur.lastrowid

    _ITEM_COLS = ("sku", "barcode", "name", "description", "brand", "unit", "purchase_unit",
                  "units_per_purchase", "sale_price", "mrp", "min_price", "taxable", "tax_code",
                  "reorder_level", "reorder_qty", "max_level", "preferred_supplier_id", "active")
    _ITEM_FLOATS = ("units_per_purchase", "sale_price", "mrp", "min_price",
                    "reorder_level", "reorder_qty", "max_level")

    def update_item(self, item_id: int, *, category=None, **fields) -> None:
        sets, vals = [], []
        if category is not None:
            sets.append("category_id=?"); vals.append(self._category_id(category))
        for k, v in fields.items():
            if k not in self._ITEM_COLS:
                raise StoreError(f"unknown item field: {k}")
            if k in self._ITEM_FLOATS:
                v = float(v)
            elif k in ("taxable", "active"):
                v = int(bool(v))
            sets.append(f"{k}=?"); vals.append(v)
        if not sets:
            return
        vals.append(item_id)
        self.s.execute(f"UPDATE store_items SET {', '.join(sets)} WHERE id=?", vals)
        self.s.commit()

    def add_supplier(self, name: str, *, contact_person: str = "", phone: str = "",
                     alt_phone: str = "", email: str = "", website: str = "",
                     address: str = "", city: str = "", state: str = "", postal_code: str = "",
                     country: str = "US", tax_id: str = "", terms: str = "",
                     lead_time_days: int = 0, bank_name: str = "", bank_account: str = "",
                     bank_routing: str = "", notes: str = "", opening_balance: float = 0.0) -> int:
        led = self._ledger(name, "Sundry Creditors", pan=(tax_id or None),
                           opening_balance=float(opening_balance or 0), opening_type="Cr")
        cur = self.s.execute(
            """INSERT INTO store_suppliers
                 (name,ledger_id,contact_person,phone,alt_phone,email,website,address,city,
                  state,postal_code,country,tax_id,terms,lead_time_days,bank_name,
                  bank_account,bank_routing,notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, led, contact_person, phone, alt_phone, email, website, address, city,
             state, postal_code, country, tax_id, terms, int(lead_time_days or 0),
             bank_name, bank_account, bank_routing, notes))
        self.s.commit()
        return cur.lastrowid

    _SUPPLIER_COLS = ("name", "contact_person", "phone", "alt_phone", "email", "website",
                      "address", "city", "state", "postal_code", "country", "tax_id", "terms",
                      "lead_time_days", "bank_name", "bank_account", "bank_routing", "active", "notes")

    def update_supplier(self, supplier_id: int, **fields) -> None:
        sets, vals = [], []
        for k, v in fields.items():
            if k not in self._SUPPLIER_COLS:
                raise StoreError(f"unknown supplier field: {k}")
            if k == "lead_time_days":
                v = int(v or 0)
            elif k == "active":
                v = int(bool(v))
            sets.append(f"{k}=?"); vals.append(v)
        if not sets:
            return
        vals.append(supplier_id)
        self.s.execute(f"UPDATE store_suppliers SET {', '.join(sets)} WHERE id=?", vals)
        self.s.commit()

    # ── valuation (perpetual weighted-average) ────────────────────────────────
    def valuate(self, item_id: int) -> dict:
        rows = self.s.execute(
            "SELECT qty, unit_cost FROM store_stock_movements WHERE item_id=? ORDER BY move_date, id",
            (item_id,)).fetchall()
        qty = value = avg = 0.0
        for r in rows:
            q = r["qty"]
            if q > 0:                       # IN at its purchase cost
                value += q * r["unit_cost"]
                qty += q
                avg = value / qty if qty > 1e-9 else 0.0
            else:                           # OUT at the current average
                value += q * avg            # q is negative → reduces value
                qty += q
                if qty <= 1e-9:
                    value = 0.0
                else:
                    avg = value / qty
        return {"on_hand": round(qty, 3), "avg_cost": round(avg, 4), "value": round(value, 2)}

    def on_hand(self, item_id: int) -> float:
        return self.valuate(item_id)["on_hand"]

    def stock_value(self) -> float:
        rows = self.s.execute("SELECT id FROM store_items WHERE active=1").fetchall()
        return round(sum(self.valuate(r["id"])["value"] for r in rows), 2)

    def low_stock(self) -> list[dict]:
        out = []
        for r in self.s.execute(
                "SELECT id,sku,name,reorder_level FROM store_items WHERE active=1").fetchall():
            oh = self.on_hand(r["id"])
            if r["reorder_level"] > 0 and oh <= r["reorder_level"]:
                out.append({"item_id": r["id"], "sku": r["sku"], "name": r["name"],
                            "on_hand": oh, "reorder_level": r["reorder_level"]})
        return out

    # ── purchasing ────────────────────────────────────────────────────────────
    def create_po(self, supplier_id: int, lines, *, po_date: str, expected_date: str = "",
                  terms: str = "", note: str = ""):
        """lines: [(item_id, qty, rate), ...]"""
        po_no = f"PO-{self.s.next_number('PO'):05d}"
        subtotal = round(sum(float(q) * float(r) for _, q, r in lines), 2)
        cur = self.s.execute(
            """INSERT INTO store_purchase_orders
                 (po_no,supplier_id,po_date,expected_date,terms,subtotal,notes)
               VALUES (?,?,?,?,?,?,?)""",
            (po_no, supplier_id, po_date, expected_date, terms, subtotal, note))
        po_id = cur.lastrowid
        for item_id, qty, rate in lines:
            self.s.execute(
                "INSERT INTO store_po_lines (po_id,item_id,qty,rate) VALUES (?,?,?,?)",
                (po_id, item_id, float(qty), float(rate)))
        self.s.commit()
        return {"po_id": po_id, "po_no": po_no}

    def receive_grn(self, supplier_id: int, lines, *, grn_date: str,
                    po_id: int | None = None, supplier_invoice_no: str = "",
                    supplier_invoice_date: str = "", due_date: str = "",
                    note: str = "") -> dict:
        """Receive stock. lines: [(item_id, qty, rate), ...]. Raises stock and posts
        a purchase voucher (Dr Stock-in-Trade / Cr Supplier) to the books."""
        sup = self.s.execute(
            "SELECT ledger_id, name FROM store_suppliers WHERE id=?", (supplier_id,)).fetchone()
        if not sup:
            raise StoreError(f"supplier {supplier_id} not found")
        grn_no = f"GRN-{self.s.next_number('GRN'):05d}"
        total = round(sum(float(q) * float(r) for _, q, r in lines), 2)

        draft = self.engine.build_purchase(
            voucher_date=grn_date,
            party_ledger_id=sup["ledger_id"],
            purchase_ledger_id=self._inventory_ledger(),
            base_amount=total,
            gst_rate_pct=self.tax,
            narration=f"GRN {grn_no} — {sup['name']}",
            reference=grn_no)
        vno = self._vno(self.engine.post(draft))

        cur = self.s.execute(
            """INSERT INTO store_grns
                 (grn_no,po_id,supplier_id,grn_date,supplier_invoice_no,
                  supplier_invoice_date,due_date,subtotal,total,voucher_no,notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (grn_no, po_id, supplier_id, grn_date, supplier_invoice_no,
             supplier_invoice_date, due_date, total, total, vno, note))
        grn_id = cur.lastrowid
        for item_id, qty, rate in lines:
            self.s.execute(
                "INSERT INTO store_grn_lines (grn_id,item_id,qty,rate) VALUES (?,?,?,?)",
                (grn_id, item_id, float(qty), float(rate)))
            self.s.execute(
                """INSERT INTO store_stock_movements
                     (item_id,move_date,qty,unit_cost,move_type,ref,voucher_no)
                   VALUES (?,?,?,?,?,?,?)""",
                (item_id, grn_date, float(qty), float(rate), "GRN", grn_no, vno))
            if po_id:
                self.s.execute(
                    "UPDATE store_po_lines SET received_qty=received_qty+? WHERE po_id=? AND item_id=?",
                    (float(qty), po_id, item_id))
        if po_id:
            self._refresh_po_status(po_id)
        self.s.commit()
        return {"grn_id": grn_id, "grn_no": grn_no, "voucher_no": vno, "total": total}

    def _refresh_po_status(self, po_id: int) -> None:
        rows = self.s.execute(
            "SELECT qty, received_qty FROM store_po_lines WHERE po_id=?", (po_id,)).fetchall()
        if rows and all(r["received_qty"] >= r["qty"] - 1e-9 for r in rows):
            st = "RECEIVED"
        elif any(r["received_qty"] > 0 for r in rows):
            st = "PARTIAL"
        else:
            st = "OPEN"
        self.s.execute("UPDATE store_purchase_orders SET status=? WHERE id=?", (st, po_id))

    # ── sale (inventory + COGS side; revenue is the billing layer's job) ───────
    def record_sale(self, lines, *, sale_date: str, ref: str = "") -> dict:
        """lines: [(item_id, qty), ...]. Reduces stock at average cost and posts a
        COGS journal (Dr Cost of Goods Sold / Cr Stock-in-Trade)."""
        cogs = 0.0
        for item_id, qty in lines:
            avg = self.valuate(item_id)["avg_cost"]
            q = float(qty)
            self.s.execute(
                """INSERT INTO store_stock_movements
                     (item_id,move_date,qty,unit_cost,move_type,ref)
                   VALUES (?,?,?,?,?,?)""",
                (item_id, sale_date, -q, avg, "SALE", ref))
            cogs += q * avg
        cogs = round(cogs, 2)
        vno = ""
        if cogs > 0:
            draft = self.engine.build_journal(
                voucher_date=sale_date,
                lines=[VoucherLine(ledger_id=self._cogs_ledger(), dr_amount=cogs),
                       VoucherLine(ledger_id=self._inventory_ledger(), cr_amount=cogs)],
                narration=f"COGS — sale {ref}", reference=ref)
            vno = self._vno(self.engine.post(draft))
            self.s.execute(
                "UPDATE store_stock_movements SET voucher_no=? WHERE ref=? AND move_type='SALE' AND voucher_no=''",
                (vno, ref))
        self.s.commit()
        return {"cogs": cogs, "voucher_no": vno}

    # ── adjustments (count / damage / shrinkage) ──────────────────────────────
    def adjust_stock(self, item_id: int, qty_delta: float, *, adj_date: str, reason: str = "") -> dict:
        avg = self.valuate(item_id)["avg_cost"]
        qd = float(qty_delta)
        self.s.execute(
            """INSERT INTO store_stock_movements
                 (item_id,move_date,qty,unit_cost,move_type,note)
               VALUES (?,?,?,?,?,?)""",
            (item_id, adj_date, qd, avg, "ADJUST", reason))
        cost = round(abs(qd) * avg, 2)
        vno = ""
        if cost > 0:
            inv, shr = self._inventory_ledger(), self._shrinkage_ledger()
            if qd < 0:   # shrinkage/wastage: Dr Shrinkage / Cr Inventory
                lines = [VoucherLine(ledger_id=shr, dr_amount=cost),
                         VoucherLine(ledger_id=inv, cr_amount=cost)]
            else:        # found stock: Dr Inventory / Cr Shrinkage
                lines = [VoucherLine(ledger_id=inv, dr_amount=cost),
                         VoucherLine(ledger_id=shr, cr_amount=cost)]
            draft = self.engine.build_journal(
                voucher_date=adj_date, lines=lines, narration=f"Stock adjust — {reason}")
            vno = self._vno(self.engine.post(draft))
            self.s.execute(
                "UPDATE store_stock_movements SET voucher_no=? WHERE item_id=? AND move_type='ADJUST' AND voucher_no='' AND move_date=?",
                (vno, item_id, adj_date))
        self.s.commit()
        return {"voucher_no": vno}

    # ── sale return: goods back to stock + reverse COGS ───────────────────────
    def return_to_stock(self, lines, *, date: str, ref: str = "") -> dict:
        """lines: [(item_id, qty), ...]. Returned goods re-enter stock at current
        average cost; reverses COGS (Dr Inventory / Cr COGS). The revenue reversal
        (credit note) is the sell-layer's job (StoreSales.return_sale)."""
        cost = 0.0
        for item_id, qty in lines:
            avg = self.valuate(item_id)["avg_cost"]
            q = float(qty)
            self.s.execute(
                """INSERT INTO store_stock_movements
                     (item_id,move_date,qty,unit_cost,move_type,ref)
                   VALUES (?,?,?,?,?,?)""",
                (item_id, date, q, avg, "RETURN", ref))
            cost += q * avg
        cost = round(cost, 2)
        vno = ""
        if cost > 0:
            draft = self.engine.build_journal(
                voucher_date=date,
                lines=[VoucherLine(ledger_id=self._inventory_ledger(), dr_amount=cost),
                       VoucherLine(ledger_id=self._cogs_ledger(), cr_amount=cost)],
                narration=f"Sale return to stock {ref}", reference=ref)
            vno = self._vno(self.engine.post(draft))
            self.s.execute(
                "UPDATE store_stock_movements SET voucher_no=? WHERE ref=? AND move_type='RETURN' AND voucher_no=''",
                (vno, ref))
        self.s.commit()
        return {"cost": cost, "voucher_no": vno}

    # ── purchase return / debit note: goods back TO the supplier ──────────────
    def purchase_return(self, supplier_id: int, lines, *, date: str, ref: str = "") -> dict:
        """lines: [(item_id, qty), ...] returned to the supplier. Stock OUT at
        current avg cost; posts the debit note Dr Supplier / Cr Inventory (reduces
        what we owe + drops stock). No tax (mirrors the rate-0 GRN)."""
        sup = self.s.execute(
            "SELECT ledger_id, name FROM store_suppliers WHERE id=?", (supplier_id,)).fetchone()
        if not sup:
            raise StoreError(f"supplier {supplier_id} not found")
        dn_no = f"DN-{self.s.next_number('DN'):05d}"
        cost = 0.0
        for item_id, qty in lines:
            avg = self.valuate(item_id)["avg_cost"]
            q = float(qty)
            self.s.execute(
                """INSERT INTO store_stock_movements
                     (item_id,move_date,qty,unit_cost,move_type,ref)
                   VALUES (?,?,?,?,?,?)""",
                (item_id, date, -q, avg, "PURCHASE_RETURN", dn_no))
            cost += q * avg
        cost = round(cost, 2)
        vno = ""
        if cost > 0:
            draft = self.engine.build_journal(
                voucher_date=date,
                lines=[VoucherLine(ledger_id=sup["ledger_id"], dr_amount=cost),   # reduce payable
                       VoucherLine(ledger_id=self._inventory_ledger(), cr_amount=cost)],  # stock out
                narration=f"Purchase return {dn_no} — {sup['name']}", reference=dn_no)
            vno = self._vno(self.engine.post(draft))
            self.s.execute(
                "UPDATE store_stock_movements SET voucher_no=? WHERE ref=? AND move_type='PURCHASE_RETURN' AND voucher_no=''",
                (vno, dn_no))
        self.s.commit()
        return {"dn_no": dn_no, "voucher_no": vno, "cost": cost}
