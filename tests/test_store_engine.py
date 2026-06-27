"""
Store HQ engine alignment test — exercises the full backend against the
comprehensive 14-table schema and asserts the books stay balanced.

Run:  python -m unittest tests.test_store_engine -v
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestStoreEngine(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="aicc_storetest_"))
        self._patcher = patch("core.models.DB_DIR", self.tmpdir)
        self._patcher.start()

        from core import country
        country.set_active("US")

        from core.models import Database
        from core.account_tree import AccountTree
        from core.voucher_engine import VoucherEngine
        from core.store import StoreDB, StoreEngine, StoreSales

        self.db = Database("storetest")
        self.db.connect()
        cur = self.db.execute(
            "INSERT INTO companies (name, gstin, state_code) VALUES (?,?,?)",
            ("StoreCo", "", "US"))
        self.company_id = cur.lastrowid
        self.db.execute("UPDATE companies SET sales_tax_rate=? WHERE id=?",
                        (8.0, self.company_id))
        self.db.commit()

        self.tree = AccountTree(self.db, self.company_id)
        self.tree.seed_defaults()
        self.engine = VoucherEngine(self.db, self.company_id)

        self.sdb = StoreDB(str(self.tmpdir / "storetest_store.db"))
        self.se = StoreEngine(self.sdb, self.engine, self.tree, default_tax_rate=0.0)
        self.ss = StoreSales(self.se, sales_tax_rate=8.0)

    def tearDown(self):
        try:
            self.sdb.close()
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass
        self._patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── helpers ───────────────────────────────────────────────────────────────
    def _assert_books_balanced(self):
        """Every voucher balances, and the whole ledger nets to zero."""
        for v in self.db.execute("SELECT id, voucher_number FROM vouchers").fetchall():
            r = self.db.execute(
                "SELECT COALESCE(SUM(dr_amount),0) d, COALESCE(SUM(cr_amount),0) c "
                "FROM voucher_lines WHERE voucher_id=?", (v["id"],)).fetchone()
            self.assertAlmostEqual(
                r["d"], r["c"], places=2,
                msg=f"voucher {v['voucher_number']} unbalanced: Dr {r['d']} Cr {r['c']}")
        net = self.db.execute(
            "SELECT COALESCE(SUM(dr_amount),0)-COALESCE(SUM(cr_amount),0) n FROM voucher_lines"
        ).fetchone()["n"]
        self.assertAlmostEqual(net or 0.0, 0.0, places=2, msg="ledger does not net to zero")

    # ── the full flow ──────────────────────────────────────────────────────────
    def test_full_flow(self):
        # 1) catalog — comprehensive add_item (category resolved to category_id)
        widget = self.se.add_item(
            "WID-1", "Widget", description="A test widget", category="Hardware",
            brand="Acme", unit="pc", purchase_unit="box", units_per_purchase=12,
            sale_price=20.0, mrp=25.0, min_price=15.0, taxable=True,
            reorder_level=5, reorder_qty=24, barcode="0001")
        gizmo = self.se.add_item("GIZ-1", "Gizmo", category="Hardware",
                                 sale_price=8.0, reorder_level=10)
        row = self.sdb.execute("SELECT * FROM store_items WHERE id=?", (widget,)).fetchone()
        self.assertIsNotNone(row["category_id"])
        self.assertEqual(row["brand"], "Acme")
        self.assertEqual(row["units_per_purchase"], 12)
        # category was auto-created and shared
        self.assertEqual(
            self.sdb.execute("SELECT COUNT(*) c FROM store_categories").fetchone()["c"], 1)

        # 2) supplier — comprehensive + opening balance to the creditor ledger
        sup = self.se.add_supplier(
            "Acme Supply", contact_person="Jane", phone="555-1000", email="jane@acme.test",
            address="1 Main St", city="Springfield", state="IL", postal_code="62701",
            tax_id="12-3456789", terms="Net 30", lead_time_days=7,
            bank_name="First Bank", bank_account="999", opening_balance=100.0)
        srow = self.sdb.execute("SELECT * FROM store_suppliers WHERE id=?", (sup,)).fetchone()
        self.assertEqual(srow["contact_person"], "Jane")
        self.assertEqual(srow["lead_time_days"], 7)

        # 3) PO then GRN (receive at cost) — books: Dr Inventory / Cr Supplier
        po = self.se.create_po(sup, [(widget, 24, 10.0), (gizmo, 50, 4.0)],
                               po_date="2026-06-01", expected_date="2026-06-05", terms="Net 30")
        self.assertTrue(po["po_no"].startswith("PO-"))
        porow = self.sdb.execute("SELECT * FROM store_purchase_orders WHERE id=?",
                                 (po["po_id"],)).fetchone()
        self.assertAlmostEqual(porow["subtotal"], 24 * 10.0 + 50 * 4.0, places=2)

        grn = self.se.receive_grn(
            sup, [(widget, 24, 10.0), (gizmo, 50, 4.0)], grn_date="2026-06-05",
            po_id=po["po_id"], supplier_invoice_no="ACM-778",
            supplier_invoice_date="2026-06-05", due_date="2026-07-05")
        grow = self.sdb.execute("SELECT * FROM store_grns WHERE id=?", (grn["grn_id"],)).fetchone()
        self.assertEqual(grow["supplier_invoice_no"], "ACM-778")
        self.assertAlmostEqual(grow["subtotal"], 440.0, places=2)
        self.assertEqual(self.se.on_hand(widget), 24)
        self.assertAlmostEqual(self.se.valuate(widget)["avg_cost"], 10.0, places=2)

        # PO should now be fully received
        self.assertEqual(
            self.sdb.execute("SELECT status FROM store_purchase_orders WHERE id=?",
                             (po["po_id"],)).fetchone()["status"], "RECEIVED")

        # 4) counter sale (Type-1) + day close
        sale = self.ss.record_counter_sale(
            [(widget, 2, 20.0), (gizmo, 3, 8.0)],
            [("CASH", 30.0), ("CARD", 39.92)], sale_date="2026-06-06")
        self.assertAlmostEqual(sale["subtotal"], 64.0, places=2)
        self.assertAlmostEqual(sale["tax"], round(64.0 * 0.08, 2), places=2)
        # line_total populated
        lt = self.sdb.execute(
            "SELECT line_total FROM store_sale_lines WHERE sale_id=? ORDER BY id",
            (sale["sale_id"],)).fetchall()
        self.assertAlmostEqual(lt[0]["line_total"], 40.0, places=2)
        self.assertEqual(self.se.on_hand(widget), 22)

        day = self.ss.close_day("2026-06-06")
        dc = self.sdb.execute("SELECT * FROM store_day_close WHERE close_date=?",
                              ("2026-06-06",)).fetchone()
        self.assertAlmostEqual(dc["total"], day["total"], places=2)
        self.assertAlmostEqual(dc["cash_total"], 30.0, places=2)

        # 5) named-customer invoice (Type-2) — add_customer makes a store_customers row
        cust_led = self.ss.add_customer(
            "Bob's Cafe", phone="555-2000", email="bob@cafe.test",
            credit_limit=500.0, terms="Net 15")
        crow = self.sdb.execute("SELECT * FROM store_customers WHERE name=?",
                                ("Bob's Cafe",)).fetchone()
        self.assertIsNotNone(crow)
        self.assertEqual(crow["ledger_id"], cust_led)
        self.assertAlmostEqual(crow["credit_limit"], 500.0, places=2)

        inv = self.ss.create_invoice(cust_led, [(widget, 1, 20.0)],
                                     sale_date="2026-06-07", customer_id=crow["id"])
        self.assertTrue(inv["invoice_no"].startswith("INV-"))
        # settle it (full), processor fee → Collection Charges
        self.ss.receive_payment(cust_led, inv["total"], date="2026-06-08",
                                to_ledger=("Bank Account", "Bank Accounts", "bank"), ref=inv["invoice_no"])

        # 6) sale return (goods back, credit the customer)
        self.ss.return_sale([(widget, 1, 20.0)], return_date="2026-06-09",
                            credit_to=("PARTY", cust_led), ref="ret-test")

        # 7) purchase return to supplier
        self.se.purchase_return(sup, [(gizmo, 5)], date="2026-06-10")

        # 8) stock adjustment (shrinkage)
        self.se.adjust_stock(gizmo, -2, adj_date="2026-06-10", reason="damage")

        # the whole thing must still balance
        self._assert_books_balanced()


if __name__ == "__main__":
    unittest.main()
