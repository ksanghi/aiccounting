"""End-to-end smoke test for Books HQ web — run from the Aiccounting dir:
    python web/_smoketest.py
Uses a throwaway data dir + app DB so it never touches real data.
"""
import os
import tempfile

_d = tempfile.mkdtemp(prefix="bookshq_test_")
os.environ["ACCGENIE_DATA_DIR"] = os.path.join(_d, "data")
os.environ["APP_DATABASE_URL"] = "sqlite:///" + os.path.join(_d, "app.db").replace("\\", "/")
os.environ["SECRET_KEY"] = "test-secret-key"

from fastapi.testclient import TestClient          # noqa: E402
from web.main import app                           # noqa: E402
from web.db import SessionLocal, init_schema       # noqa: E402
from web.models import CompanyRef                  # noqa: E402
from web import engine_bridge                      # noqa: E402

init_schema()  # TestClient doesn't fire startup events outside a context manager

# https base_url so the Secure session cookie is stored + replayed.
c = TestClient(app, base_url="https://testserver")


def check(label, cond):
    print(("  OK " if cond else " FAIL") + " | " + label)
    if not cond:
        raise SystemExit("SMOKE TEST FAILED: " + label)


r = c.post("/signup", data={"name": "Test", "email": "t@example.com",
                            "password": "password1"}, follow_redirects=False)
check(f"signup -> {r.status_code} {r.headers.get('location')}", r.status_code == 303)

r = c.post("/companies", data={"display_name": "Acme US Inc"}, follow_redirects=False)
check(f"create company -> {r.status_code}", r.status_code == 303)
slug = r.headers["location"].split("/c/")[1].strip("/")
print("  slug:", slug)

r = c.get(f"/c/{slug}/")
check(f"dashboard {r.status_code}", r.status_code == 200 and "Acme US Inc" in r.text)

r = c.get(f"/c/{slug}/ledgers")
check(f"ledgers page {r.status_code}", r.status_code == 200)

# Use the engine to fetch seeded ledger ids + add an expense ledger.
s = SessionLocal()
ref = s.query(CompanyRef).filter_by(slug=slug).first()
tree = engine_bridge.tree_for(slug, ref.company_id)
leds = {lg["name"]: lg["id"] for lg in tree.get_all_ledgers()}
print("  seeded ledgers:", len(leds))
cash_id = leds.get("Cash")
check("Cash ledger seeded", bool(cash_id))
exp_id = tree.add_ledger("Office Rent", "Indirect Expenses")
check("add expense ledger", bool(exp_id))

# Post a PAYMENT: Dr Office Rent, Cr Cash.
r = c.post(f"/c/{slug}/vouchers",
           data={"vtype": "PAYMENT", "voucher_date": "2026-02-01",
                 "ledger_a": exp_id, "ledger_b": cash_id, "amount": "1500",
                 "narration": "Feb office rent"}, follow_redirects=False)
check(f"post payment -> {r.status_code} {r.headers.get('location')}", r.status_code == 303)

# Post a SALES voucher with a customer + sales account + 8% sales tax.
cust_id = tree.add_ledger("Acme Customer", "Sundry Debtors")
sales_id = leds.get("Sales") or tree.add_ledger("Sales", "Sales Accounts")
r = c.post(f"/c/{slug}/vouchers",
           data={"vtype": "SALES", "voucher_date": "2026-02-05",
                 "ledger_a": cust_id, "ledger_b": sales_id, "amount": "1000",
                 "gst_rate": "8", "narration": "Invoice 1"}, follow_redirects=False)
check(f"post sales -> {r.status_code}", r.status_code == 303)

r = c.get(f"/c/{slug}/vouchers")
check("daybook shows payment", "Feb office rent" in r.text)

for path, label in [("trial-balance", "Trial Balance"), ("pnl", "P&L"),
                    ("balance-sheet", "Balance Sheet"), ("receivables", "A/R"),
                    ("payables", "A/P"), ("schedule-c", "Schedule C"),
                    ("form-1099", "Form 1099")]:
    r = c.get(f"/c/{slug}/reports/{path}")
    check(f"report {label} {r.status_code}", r.status_code == 200)

print("\nALL SMOKE CHECKS PASSED")
