"""Offscreen smoke test for the Store HQ UI — builds the window, every page, and
each create/edit dialog, and drives an add-item through the engine. Run with:
    QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 python tests/_store_ui_smoke.py
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

tmp = Path(tempfile.mkdtemp(prefix="aicc_storeui_"))
p = patch("core.models.DB_DIR", tmp); p.start()

from core import country
country.set_active("US")

from PySide6.QtWidgets import QApplication
from core.models import Database
from core.account_tree import AccountTree
from core.voucher_engine import VoucherEngine
from core.store import StoreDB, StoreEngine, StoreSales

app = QApplication(sys.argv)

db = Database("uitest"); db.connect()
cid = db.execute("INSERT INTO companies (name, gstin, state_code) VALUES (?,?,?)",
                 ("UICo", "", "US")).lastrowid
db.execute("UPDATE companies SET sales_tax_rate=8 WHERE id=?", (cid,))
db.commit()
tree = AccountTree(db, cid); tree.seed_defaults()
eng = VoucherEngine(db, cid)
sdb = StoreDB(str(tmp / "uitest_store.db"))
se = StoreEngine(sdb, eng, tree)
ss = StoreSales(se, sales_tax_rate=8)

# seed a bit of data so edit/picker paths have rows
iid = se.add_item("SKU-1", "Test Widget", category="Hardware", sale_price=12.0, reorder_level=3)
sid = se.add_supplier("Acme", contact_person="Jane", phone="555")

from ui.store.store_window import StoreWindow
from ui.store.inventory_page import InventoryPage, _ItemDialog, _AdjustDialog
from ui.store.purchasing_page import (
    PurchasingPage, _SupplierDialog, _SupplierManager, _LineDialog)
from ui.store.pos_page import POSPage, _InvoiceDialog

errors = []

def check(label, fn):
    try:
        fn(); print(f"OK  {label}")
    except Exception as e:
        errors.append((label, e)); print(f"ERR {label}: {e!r}")

# window + pages
win = StoreWindow(se, ss, company_name="UICo")
check("StoreWindow built", lambda: win)
check("InventoryPage", lambda: InventoryPage(se))
check("PurchasingPage", lambda: PurchasingPage(se))
check("POSPage", lambda: POSPage(ss, se))

# dialogs — construct + values()
cats = ["Hardware", "Grocery"]
check("ItemDialog(new).values", lambda: _ItemDialog(cats).values())
itemrow = sdb.execute(
    "SELECT i.*, c.name AS category FROM store_items i "
    "LEFT JOIN store_categories c ON c.id=i.category_id WHERE i.id=?", (iid,)).fetchone()
check("ItemDialog(edit).values", lambda: _ItemDialog(cats, existing=itemrow).values())
items = sdb.execute("SELECT id, sku, name FROM store_items").fetchall()
check("AdjustDialog.values", lambda: _AdjustDialog(items, iid).values())
check("SupplierDialog(new).values", lambda: _SupplierDialog().values())
suprow = sdb.execute("SELECT * FROM store_suppliers WHERE id=?", (sid,)).fetchone()
check("SupplierDialog(edit).values", lambda: _SupplierDialog(existing=suprow).values_no_name())
check("SupplierManager built", lambda: _SupplierManager(se))
check("LineDialog(PO).values", lambda: _LineDialog("PO", se, mode="PO").values())
check("LineDialog(GRN).values", lambda: _LineDialog("GRN", se, mode="GRN").values()
      if True else None)
po = se.create_po(sid, [(iid, 5, 8.0)], po_date="2026-06-01")
porow = sdb.execute("SELECT * FROM store_purchase_orders WHERE id=?", (po["po_id"],)).fetchone()
check("LineDialog(GRN from PO) prefill", lambda: _LineDialog("GRN", se, mode="GRN", po=porow))
items2 = sdb.execute("SELECT id, sku, name, sale_price FROM store_items").fetchall()
check("InvoiceDialog.values", lambda: _InvoiceDialog(items2).values())

# drive an edit through the engine (what F3 does)
def do_edit():
    se.update_item(iid, name="Renamed Widget", sale_price=15.0, category="Grocery")
    r = sdb.execute("SELECT name, sale_price FROM store_items WHERE id=?", (iid,)).fetchone()
    assert r["name"] == "Renamed Widget" and abs(r["sale_price"] - 15.0) < 1e-6
check("update_item (F3 edit)", do_edit)

def do_sup_edit():
    se.update_supplier(sid, phone="999-0000", city="Springfield")
    r = sdb.execute("SELECT phone, city FROM store_suppliers WHERE id=?", (sid,)).fetchone()
    assert r["phone"] == "999-0000" and r["city"] == "Springfield"
check("update_supplier (F3 edit)", do_sup_edit)

sdb.close(); db.close()
print("\n" + ("ALL UI SMOKE CHECKS PASSED" if not errors else f"{len(errors)} FAILURES"))
sys.exit(1 if errors else 0)
