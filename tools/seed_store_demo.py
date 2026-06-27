"""
DEV-ONLY: seed realistic dummy data into a company's Store HQ DB so every screen
has something to show. Idempotent — does nothing if items already exist.

    python tools/seed_store_demo.py [company_slug]     (default krishan_sanghi_us)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import country, branding
country.set_active("US")
country.reset_active = lambda: None
branding.apply_country_branding()

from core.models import Database
from core.account_tree import AccountTree
from core.voucher_engine import VoucherEngine
from core.store import StoreDB, StoreEngine, StoreSales


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "krishan_sanghi_us"
    db = Database(slug); db.connect()
    row = db.execute("SELECT id, name FROM companies LIMIT 1").fetchone()
    if not row:
        print(f"No company in {slug}.db"); return
    cid = row["id"]
    # make sure the store sells with a tax rate
    db.execute("UPDATE companies SET sales_tax_rate=COALESCE(NULLIF(sales_tax_rate,0),8.25) WHERE id=?", (cid,))
    db.commit()
    tree = AccountTree(db, cid)
    eng = VoucherEngine(db, cid)
    se = StoreEngine(StoreDB.for_company(slug), eng, tree)
    ss = StoreSales(se)

    if se.s.execute("SELECT 1 FROM store_items LIMIT 1").fetchone():
        print("Store already has items — skipping seed (delete the *_store.db to reseed).")
        se.s.close(); db.close(); return

    # ── catalog ──────────────────────────────────────────────────────────────
    items = {}
    catalog = [
        ("BEV-001", "Cola 500ml", "Beverages", "Fizz", 1.50, 1.99, 24, 48, "0010"),
        ("BEV-002", "Spring Water 1L", "Beverages", "AquaPure", 0.99, 1.29, 30, 60, "0011"),
        ("BEV-003", "Coffee Beans 1kg", "Beverages", "Roastery", 12.00, 15.99, 6, 12, "0012"),
        ("SNK-001", "Potato Chips 150g", "Snacks", "CrunchCo", 2.25, 2.99, 20, 40, "0020"),
        ("SNK-002", "Chocolate Bar", "Snacks", "CocoaJoy", 1.20, 1.50, 36, 72, "0021"),
        ("HSE-001", "Dish Soap 500ml", "Household", "Sparkle", 3.49, 4.29, 12, 24, "0030"),
        ("HSE-002", "Paper Towels 6pk", "Household", "SoftRoll", 5.99, 7.49, 10, 20, "0031"),
    ]
    for sku, name, cat, brand, price, mrp, rl, rq, bc in catalog:
        items[sku] = se.add_item(sku, name, category=cat, brand=brand, sale_price=price,
                                 mrp=mrp, reorder_level=rl, reorder_qty=rq, barcode=bc,
                                 unit="pc", purchase_unit="case", units_per_purchase=12)

    # ── suppliers ──────────────────────────────────────────────────────────────
    acme = se.add_supplier("Acme Distributors", contact_person="Maria Lopez", phone="312-555-0100",
                           email="orders@acme.test", website="acme.test", address="500 Industrial Rd",
                           city="Chicago", state="IL", postal_code="60607", tax_id="36-1234567",
                           terms="Net 30", lead_time_days=5, bank_name="First National",
                           bank_account="00112233", notes="Primary beverage + snack supplier.")
    fresh = se.add_supplier("FreshFoods Inc", contact_person="Tom Reed", phone="312-555-0200",
                            email="sales@freshfoods.test", city="Chicago", state="IL",
                            postal_code="60616", terms="Net 15", lead_time_days=3)
    se.add_supplier("CleanCo Supplies", contact_person="Dana Kim", phone="312-555-0300",
                    email="hello@cleanco.test", city="Naperville", state="IL", terms="Net 30",
                    opening_balance=120.00)

    # ── customers ──────────────────────────────────────────────────────────────
    cafe = ss.add_customer("Downtown Cafe", contact_person="Ana", phone="312-555-0400",
                           email="ana@downtowncafe.test", terms="Net 15", credit_limit=2000.0)
    ss.add_customer("Bob's Diner", phone="312-555-0500", email="bob@bobsdiner.test", credit_limit=1000.0)
    cafe_row = se.s.execute("SELECT id FROM store_customers WHERE name='Downtown Cafe'").fetchone()

    # ── purchasing: PO then GRN, plus a direct GRN ──────────────────────────────
    po = se.create_po(acme, [(items["BEV-001"], 48, 0.90), (items["BEV-003"], 12, 8.00),
                             (items["SNK-001"], 40, 1.40)],
                      po_date="2026-06-02", expected_date="2026-06-06", terms="Net 30")
    se.receive_grn(acme, [(items["BEV-001"], 48, 0.90), (items["BEV-003"], 12, 8.00),
                          (items["SNK-001"], 40, 1.40)],
                   grn_date="2026-06-06", po_id=po["po_id"], supplier_invoice_no="ACM-5521",
                   supplier_invoice_date="2026-06-06", due_date="2026-07-06")
    se.receive_grn(fresh, [(items["BEV-002"], 60, 0.55), (items["SNK-002"], 72, 0.70)],
                   grn_date="2026-06-04", supplier_invoice_no="FF-7781", due_date="2026-06-19")
    se.receive_grn(acme, [(items["HSE-001"], 24, 2.10), (items["HSE-002"], 20, 3.80)],
                   grn_date="2026-06-05", supplier_invoice_no="ACM-5530", due_date="2026-07-05")

    # ── counter sales across a couple of days, then close them ──────────────────
    ss.record_counter_sale([(items["BEV-001"], 3, 1.50), (items["SNK-001"], 2, 2.25)],
                           [("CASH", 11.30)], sale_date="2026-06-07")
    ss.record_counter_sale([(items["BEV-002"], 4, 0.99), (items["SNK-002"], 5, 1.20)],
                           [("CARD", 10.78)], sale_date="2026-06-07")
    ss.record_counter_sale([(items["BEV-003"], 1, 12.00), (items["HSE-001"], 2, 3.49)],
                           [("UPI", 20.49)], sale_date="2026-06-07")
    ss.close_day("2026-06-07")
    ss.record_counter_sale([(items["SNK-001"], 6, 2.25), (items["BEV-001"], 6, 1.50)],
                           [("CASH", 24.32)], sale_date="2026-06-08")
    ss.close_day("2026-06-08")

    # ── named-customer invoice + part payment ───────────────────────────────────
    inv = ss.create_invoice(cafe, [(items["BEV-003"], 3, 12.00), (items["SNK-002"], 20, 1.20)],
                            sale_date="2026-06-08", customer_id=(cafe_row["id"] if cafe_row else None))
    ss.receive_payment(cafe, 30.00, date="2026-06-09",
                       to_ledger=("Bank Account", "Bank Accounts", "bank"), ref=inv["invoice_no"])

    # ── a sale return + a purchase return + a shrinkage adjustment ───────────────
    ss.return_sale([(items["SNK-002"], 2, 1.20)], return_date="2026-06-09",
                   credit_to=("PARTY", cafe), ref="cn-demo")
    se.purchase_return(acme, [(items["HSE-002"], 2)], date="2026-06-09")
    se.adjust_stock(items["BEV-002"], -3, adj_date="2026-06-09", reason="breakage")

    n_items = se.s.execute("SELECT COUNT(*) c FROM store_items").fetchone()["c"]
    n_sales = se.s.execute("SELECT COUNT(*) c FROM store_sales").fetchone()["c"]
    print(f"Seeded {n_items} items, 3 suppliers, 2 customers, POs/GRNs, {n_sales} sale rows, "
          f"returns + adjustment into {slug}_store.db (books posted in {slug}.db).")
    se.s.close(); db.close()


if __name__ == "__main__":
    main()
