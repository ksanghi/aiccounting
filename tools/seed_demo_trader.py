"""
Seed a realistic demo TRADER company for manual screenshots.

Run against the INSTALLED app's data dir so the company shows in 1.0's picker:
    ACCGENIE_DATA_DIR must be set to %APPDATA%\\AccGenie BEFORE importing core
    (DB_DIR resolves at import time). This script sets it from --data-dir.

Usage:
    python tools/seed_demo_trader.py --data-dir "C:/Users/<you>/AppData/Roaming/AccGenie"
    python tools/seed_demo_trader.py --data-dir /tmp/seedtest        # dry test

Idempotent: deletes the demo .db first, so re-runs give a clean book.
"""
import argparse
import os
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--data-dir", required=True,
                help="Root that holds the companies/ folder (the app's data dir).")
args = ap.parse_args()

# MUST be set before any core import — DB_DIR is resolved at import time.
os.environ["ACCGENIE_DATA_DIR"] = str(Path(args.data_dir).resolve())

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.models       import Database                       # noqa: E402
from core.account_tree import AccountTree                    # noqa: E402
from core.voucher_engine import VoucherEngine, VoucherLine   # noqa: E402

NAME  = "Sharma Trading Co."
SLUG  = "sharma_trading_co"
GSTIN = "07ABCDS1234F1Z5"     # 07 = Delhi
STATE = "07"

# ── wipe any prior demo db so re-runs are clean ────────────────────────────
db_path = Path(os.environ["ACCGENIE_DATA_DIR"]) / "companies" / f"{SLUG}.db"
for p in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")):
    if p.exists():
        p.unlink()

db   = Database(SLUG)
conn = db.connect()
conn.execute(
    "INSERT OR IGNORE INTO companies (name, gstin, pan, state_code) VALUES (?,?,?,?)",
    (NAME, GSTIN, "ABCDS1234F", STATE),
)
db.commit()
company_id = conn.execute("SELECT id FROM companies WHERE name=?", (NAME,)).fetchone()["id"]

tree = AccountTree(db, company_id)
tree.seed_defaults()

conn.execute(
    "INSERT OR IGNORE INTO financial_years (company_id, fy, start_date, end_date) VALUES (?,?,?,?)",
    (company_id, "2026-27", "2026-04-01", "2027-03-31"),
)
db.commit()

# ── trader-specific ledgers ────────────────────────────────────────────────
bank = tree.add_ledger("HDFC Bank Current A/c", "Bank Accounts",
                       is_bank=True, state_code=STATE,
                       bank_name="HDFC Bank", account_number="50200012345678",
                       ifsc="HDFC0001234")

# customers (state drives intra vs inter-state GST)
cust = {
    "Verma Electronics":  tree.add_ledger("Verma Electronics",  "Sundry Debtors", state_code="07", gstin="07AABCV1111A1Z2"),
    "Mumbai Traders":     tree.add_ledger("Mumbai Traders",     "Sundry Debtors", state_code="27", gstin="27AAACM2222B1Z3"),
    "Bengaluru Gadgets":  tree.add_ledger("Bengaluru Gadgets",  "Sundry Debtors", state_code="29", gstin="29AAFCB3333C1Z4"),
    "Chandni Chowk Retail": tree.add_ledger("Chandni Chowk Retail", "Sundry Debtors", state_code="07", gstin="07AAGCC4444D1Z5"),
}
# suppliers
supp = {
    "Delhi Wholesale Supplies": tree.add_ledger("Delhi Wholesale Supplies", "Sundry Creditors", state_code="07", gstin="07AAACD5555E1Z6"),
    "Surat Textiles":           tree.add_ledger("Surat Textiles",           "Sundry Creditors", state_code="24", gstin="24AAFCS6666F1Z7"),
    "Noida Components":         tree.add_ledger("Noida Components",         "Sundry Creditors", state_code="09", gstin="09AAGCN7777G1Z8"),
}
sales_ldg = tree.add_ledger("Sales - Goods",     "Sales Accounts",    hsn_code="8517")
purch_ldg = tree.add_ledger("Purchases - Goods", "Purchase Accounts", hsn_code="8517")

def L(name):
    return tree.find_ledger_by_name(name)["id"] if hasattr(tree, "find_ledger_by_name") else \
        next(x["id"] for x in tree.get_all_ledgers() if x["name"] == name)

cash    = L("Cash")
capital = L("Capital Account")
rent    = L("Rent")
salary  = L("Salary")
phone   = L("Telephone & Internet")

engine = VoucherEngine(db, company_id, user_id=None)

posted = 0
def post(draft, label):
    global posted
    engine.post(draft)
    posted += 1

# ── opening capital (journal) ──────────────────────────────────────────────
post(engine.build_journal("2026-04-01",
        [VoucherLine(bank, dr_amount=500000), VoucherLine(capital, cr_amount=500000)],
        "Opening capital introduced", "OB-01"), "opening")

# ── the working book: (date, kind, *args) ──────────────────────────────────
# kind: P=purchase  S=sales  RC=receipt  PM=payment(expense/supplier)  CN=contra
BOOK = [
    ("2026-04-02", "P",  "Delhi Wholesale Supplies", 80000, 18, "Purchase of mobile accessories", "PB-101"),
    ("2026-04-03", "P",  "Surat Textiles",           60000, 12, "Purchase of fabric stock",       "PB-102"),
    ("2026-04-05", "CN", "bank2cash", 20000, "Cash drawn for petty expenses"),
    ("2026-04-06", "S",  "Verma Electronics",   55000, 18, "Sale of mobile accessories", "SB-201"),
    ("2026-04-08", "S",  "Mumbai Traders",      90000, 18, "Sale of electronic goods",   "SB-202"),
    ("2026-04-10", "PM", "Rent",                25000, "Office rent April",   "PMT-301"),
    ("2026-04-10", "PM", "Telephone & Internet", 3200, "Internet & phone April", "PMT-302"),
    ("2026-04-15", "RC", "Verma Electronics",   64900, "Received against SB-201", "RCT-401"),
    ("2026-04-18", "S",  "Bengaluru Gadgets",   72000, 18, "Sale of gadgets",  "SB-203"),
    ("2026-04-20", "PM", "Delhi Wholesale Supplies", 50000, "Part payment PB-101", "PMT-303"),
    ("2026-04-22", "P",  "Noida Components",     45000, 28, "Purchase of components", "PB-103"),
    ("2026-04-25", "S",  "Chandni Chowk Retail", 38000, 12, "Retail sale", "SB-204"),
    ("2026-04-28", "RC", "Mumbai Traders",      106200, "Received against SB-202", "RCT-402"),
    ("2026-04-30", "PM", "Salary",               40000, "Staff salary April", "PMT-304"),

    ("2026-05-02", "P",  "Delhi Wholesale Supplies", 95000, 18, "Restock accessories", "PB-104"),
    ("2026-05-04", "S",  "Verma Electronics",   60000, 18, "Sale of accessories", "SB-205"),
    ("2026-05-06", "S",  "Mumbai Traders",      48000, 5,  "Sale of low-rate goods", "SB-206"),
    ("2026-05-08", "RC", "Bengaluru Gadgets",   84960, "Received against SB-203", "RCT-403"),
    ("2026-05-10", "PM", "Rent",                25000, "Office rent May", "PMT-305"),
    ("2026-05-10", "PM", "Telephone & Internet", 3200, "Internet & phone May", "PMT-306"),
    ("2026-05-12", "CN", "cash2bank", 15000, "Surplus cash deposited"),
    ("2026-05-15", "S",  "Chandni Chowk Retail", 41000, 18, "Retail sale", "SB-207"),
    ("2026-05-18", "P",  "Surat Textiles",       52000, 12, "Fabric restock", "PB-105"),
    ("2026-05-20", "RC", "Verma Electronics",   70800, "Received against SB-205", "RCT-404"),
    ("2026-05-22", "PM", "Noida Components",     57600, "Settled PB-103", "PMT-307"),
    ("2026-05-25", "S",  "Mumbai Traders",      67000, 18, "Sale of electronics", "SB-208"),
    ("2026-05-28", "PM", "Delhi Wholesale Supplies", 60000, "Part payment PB-104", "PMT-308"),
    ("2026-05-30", "PM", "Salary",               40000, "Staff salary May", "PMT-309"),

    ("2026-06-02", "S",  "Verma Electronics",   58000, 18, "Sale of accessories", "SB-209"),
    ("2026-06-03", "P",  "Noida Components",     38000, 28, "Component purchase", "PB-106"),
    ("2026-06-05", "RC", "Chandni Chowk Retail", 48380, "Received against SB-207", "RCT-405"),
    ("2026-06-06", "PM", "Telephone & Internet", 3200, "Internet & phone June", "PMT-310"),
]

for row in BOOK:
    d, kind = row[0], row[1]
    if kind == "P":
        _, _, party, amt, rate, narr, ref = row
        post(engine.build_purchase(d, supp[party], purch_ldg, amt, rate, narr, ref), ref)
    elif kind == "S":
        _, _, party, amt, rate, narr, ref = row
        post(engine.build_sales(d, cust[party], sales_ldg, amt, rate, narr, ref), ref)
    elif kind == "RC":
        _, _, party, amt, narr, ref = row
        post(engine.build_receipt(d, cust[party], bank, amt, narr, ref), ref)
    elif kind == "PM":
        _, _, who, amt, narr, ref = row
        dr = supp.get(who) or {"Rent": rent, "Salary": salary, "Telephone & Internet": phone}[who]
        post(engine.build_payment(d, dr, bank, amt, narr, ref), ref)
    elif kind == "CN":
        _, _, direction, amt, narr = row
        frm, to = (bank, cash) if direction == "bank2cash" else (cash, bank)
        post(engine.build_contra(d, frm, to, amt, narr), narr)

# depreciation journal at period end
deprec = L("Depreciation")
post(engine.build_journal("2026-06-06",
        [VoucherLine(deprec, dr_amount=8000), VoucherLine(bank, cr_amount=8000)],
        "Depreciation on equipment", "JV-01"), "deprec")

print(f"OK: '{NAME}' seeded at {db_path}")
print(f"    {posted} vouchers posted across Apr-Jun 2026 (FY 2026-27).")
print(f"    Ledgers: {len(tree.get_all_ledgers())} total.")
