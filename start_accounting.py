"""
START_ACCOUNTING.PY
===================
Run this file to start the accounting system.

Usage:
    python start_accounting.py

This is the single entry point. Run it from ANYWHERE —
it automatically finds all other files.
"""
import sys
import os

# ── Make sure Python can find the core/ folder no matter where you run from ──
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from core.models       import Database
from core.account_tree import AccountTree
from core.voucher_engine import (
    VoucherEngine, VoucherDraft, VoucherLine, VoucherValidationError
)


def setup_company():
    """First-time setup — creates your company and seeds accounts."""
    print("\n" + "="*55)
    print("  ACCOUNTING SYSTEM — FIRST TIME SETUP")
    print("="*55)
    print("\nEnter your company details (press Enter to skip optional fields)\n")

    name       = input("  Company name          : ").strip()
    gstin      = input("  GSTIN (optional)      : ").strip()
    pan        = input("  PAN (optional)        : ").strip()
    state_code = input("  GST State code [07]   : ").strip() or "07"

    slug = name.lower().replace(" ", "_").replace(".", "")[:30]

    db  = Database(slug)
    conn = db.connect()

    # Create company
    cur = conn.execute(
        "INSERT OR IGNORE INTO companies (name, gstin, pan, state_code) VALUES (?,?,?,?)",
        (name, gstin, pan, state_code)
    )
    db.commit()

    row = conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()
    company_id = row["id"]

    # Seed chart of accounts
    tree = AccountTree(db, company_id)
    tree.seed_defaults()

    # Setup FY 2025-26
    conn.execute(
        "INSERT OR IGNORE INTO financial_years (company_id, fy, start_date, end_date) VALUES (?,?,?,?)",
        (company_id, "2025-26", "2025-04-01", "2026-03-31")
    )
    db.commit()

    print(f"\n  Company '{name}' created successfully!")
    print(f"  Database: data/companies/{slug}.db")
    print(f"  Chart of accounts seeded with {len(tree.get_all_ledgers())} default ledgers.\n")
    return db, company_id, tree


def load_company():
    """Load an existing company."""
    import glob
    from pathlib import Path

    db_dir = Path(THIS_DIR) / "data" / "companies"
    files  = list(db_dir.glob("*.db"))

    if not files:
        return None, None, None

    print("\n  Existing companies:")
    for i, f in enumerate(files, 1):
        db_tmp = Database(f.stem)
        row = db_tmp.execute("SELECT name FROM companies LIMIT 1").fetchone()
        cname = row["name"] if row else f.stem
        print(f"  [{i}] {cname}")
        db_tmp.close()

    choice = input("\n  Select company number: ").strip()
    try:
        idx = int(choice) - 1
        slug = files[idx].stem
    except (ValueError, IndexError):
        print("  Invalid choice.")
        return None, None, None

    db  = Database(slug)
    row = db.execute("SELECT id FROM companies LIMIT 1").fetchone()
    if not row:
        print("  Company data not found.")
        return None, None, None

    company_id = row["id"]
    tree = AccountTree(db, company_id)
    return db, company_id, tree


def post_voucher_interactive(engine, tree):
    """Simple text-mode voucher entry."""
    ledgers = tree.get_all_ledgers()

    def find_ledger(query):
        query = query.lower().strip()
        matches = [l for l in ledgers if query in l["name"].lower()]
        if not matches:
            print(f"  No ledger matching '{query}'")
            return None
        if len(matches) == 1:
            return matches[0]
        print("  Multiple matches:")
        for i, m in enumerate(matches, 1):
            print(f"    [{i}] {m['name']} ({m['group_name']})")
        try:
            idx = int(input("  Choose: ")) - 1
            return matches[idx]
        except (ValueError, IndexError):
            return None

    print("\n  Voucher types: payment  receipt  contra  journal  sales  purchase  debit_note  credit_note")
    vtype = input("  Voucher type  : ").strip().upper().replace(" ", "_")
    if vtype not in ("PAYMENT","RECEIPT","CONTRA","JOURNAL","SALES","PURCHASE","DEBIT_NOTE","CREDIT_NOTE"):
        print("  Invalid voucher type.")
        return

    vdate  = input("  Date (YYYY-MM-DD) [today]: ").strip()
    if not vdate:
        from datetime import date
        vdate = date.today().isoformat()

    narration = input("  Narration     : ").strip()
    reference = input("  Reference/Cheque no (optional): ").strip()

    try:
        if vtype == "PAYMENT":
            print("\n  Dr  — Expense / Party ledger")
            dr_ldg = find_ledger(input("    Search ledger : "))
            if not dr_ldg: return
            print("  Cr  — Bank / Cash ledger")
            cr_ldg = find_ledger(input("    Search ledger : "))
            if not cr_ldg: return
            amount = float(input("  Amount (₹)    : "))
            draft  = engine.build_payment(vdate, dr_ldg["id"], cr_ldg["id"], amount, narration, reference)

        elif vtype == "RECEIPT":
            print("\n  Dr  — Bank / Cash ledger")
            dr_ldg = find_ledger(input("    Search ledger : "))
            if not dr_ldg: return
            print("  Cr  — Party / Income ledger")
            cr_ldg = find_ledger(input("    Search ledger : "))
            if not cr_ldg: return
            amount = float(input("  Amount (₹)    : "))
            draft  = engine.build_receipt(vdate, cr_ldg["id"], dr_ldg["id"], amount, narration, reference)

        elif vtype == "CONTRA":
            print("\n  From (Cr) — Bank / Cash")
            from_ldg = find_ledger(input("    Search ledger : "))
            if not from_ldg: return
            print("  To   (Dr) — Bank / Cash")
            to_ldg = find_ledger(input("    Search ledger : "))
            if not to_ldg: return
            amount = float(input("  Amount (₹)    : "))
            draft  = engine.build_contra(vdate, from_ldg["id"], to_ldg["id"], amount, narration)

        elif vtype == "SALES":
            print("\n  Party (Debtor) ledger")
            party  = find_ledger(input("    Search ledger : "))
            if not party: return
            print("  Sales ledger")
            sales  = find_ledger(input("    Search ledger : "))
            if not sales: return
            amount   = float(input("  Base amount (₹) (excl. GST): "))
            gst_rate = float(input("  GST rate % [18]: ").strip() or "18")
            draft    = engine.build_sales(vdate, party["id"], sales["id"], amount, gst_rate, narration, reference)

        elif vtype == "PURCHASE":
            print("\n  Party (Creditor) ledger")
            party  = find_ledger(input("    Search ledger : "))
            if not party: return
            print("  Purchase ledger")
            purch  = find_ledger(input("    Search ledger : "))
            if not purch: return
            amount   = float(input("  Base amount (₹) (excl. GST): "))
            gst_rate = float(input("  GST rate % [18]: ").strip() or "18")
            draft    = engine.build_purchase(vdate, party["id"], purch["id"], amount, gst_rate, narration, reference)

        elif vtype == "JOURNAL":
            lines = []
            print("\n  Enter journal lines. Type 'done' when finished.")
            while True:
                print(f"\n  Line {len(lines)+1}:")
                q = input("    Ledger search (or 'done'): ").strip()
                if q.lower() == "done":
                    break
                ldg = find_ledger(q)
                if not ldg: continue
                dr = input(f"    Dr amount for {ldg['name']} (0 if Cr): ").strip()
                cr = input(f"    Cr amount for {ldg['name']} (0 if Dr): ").strip()
                lines.append(VoucherLine(
                    ledger_id=ldg["id"],
                    dr_amount=float(dr or 0),
                    cr_amount=float(cr or 0),
                ))
            draft = engine.build_journal(vdate, lines, narration, reference)

        elif vtype == "DEBIT_NOTE":
            print("\n  Party (Creditor) ledger")
            party = find_ledger(input("    Search ledger : "))
            if not party: return
            print("  Purchase Return ledger")
            pr    = find_ledger(input("    Search ledger : "))
            if not pr: return
            amount   = float(input("  Base amount (₹) (excl. GST): "))
            gst_rate = float(input("  GST rate % [18]: ").strip() or "18")
            draft    = engine.build_debit_note(vdate, party["id"], pr["id"], amount, gst_rate, narration, reference)

        elif vtype == "CREDIT_NOTE":
            print("\n  Party (Debtor) ledger")
            party = find_ledger(input("    Search ledger : "))
            if not party: return
            print("  Sales Return ledger")
            sr    = find_ledger(input("    Search ledger : "))
            if not sr: return
            amount   = float(input("  Base amount (₹) (excl. GST): "))
            gst_rate = float(input("  GST rate % [18]: ").strip() or "18")
            draft    = engine.build_credit_note(vdate, party["id"], sr["id"], amount, gst_rate, narration, reference)

        # Show draft before posting
        print("\n  ── Draft Voucher ──────────────────────────────")
        print(f"  Type   : {draft.voucher_type}")
        print(f"  Date   : {draft.voucher_date}")
        print(f"  Narrn  : {draft.narration}")
        print(f"  {'Ledger':<35} {'Dr':>12} {'Cr':>12}")
        print(f"  {'-'*35} {'-'*12} {'-'*12}")
        for l in draft.lines:
            row = engine.db.execute("SELECT name FROM ledgers WHERE id=?", (l.ledger_id,)).fetchone()
            name = row["name"] if row else str(l.ledger_id)
            dr = f"₹{l.dr_amount:>10,.2f}" if l.dr_amount else ""
            cr = f"₹{l.cr_amount:>10,.2f}" if l.cr_amount else ""
            print(f"  {name:<35} {dr:>12} {cr:>12}")
        print(f"  {'-'*35} {'-'*12} {'-'*12}")
        print(f"  {'Total':<35} ₹{draft.total_dr:>10,.2f} ₹{draft.total_cr:>10,.2f}")
        print(f"  Balanced: {'YES ✓' if draft.is_balanced else 'NO ✗'}")

        confirm = input("\n  Post this voucher? (y/n): ").strip().lower()
        if confirm == "y":
            posted = engine.post(draft)
            print(f"\n  ✓ Posted: {posted.voucher_number} | ₹{posted.total_amount:,.2f}")
        else:
            print("  Voucher discarded.")

    except VoucherValidationError as e:
        print(f"\n  ✗ Validation failed:")
        for err in e.errors:
            print(f"    - {err}")
    except Exception as e:
        print(f"\n  ✗ Error: {e}")


def view_daybook(engine):
    """Show recent vouchers."""
    from_date = input("  From date (YYYY-MM-DD) [leave blank = all]: ").strip() or None
    to_date   = input("  To   date (YYYY-MM-DD) [leave blank = all]: ").strip() or None
    vouchers  = engine.list_vouchers(from_date=from_date, to_date=to_date)
    if not vouchers:
        print("  No vouchers found.")
        return
    print(f"\n  {'Date':<12} {'Voucher No':<22} {'Amount':>12}  Narration")
    print(f"  {'-'*12} {'-'*22} {'-'*12}  {'-'*30}")
    for v in vouchers:
        status = " [CANCELLED]" if v["is_cancelled"] else ""
        print(f"  {v['voucher_date']:<12} {v['voucher_number']:<22} ₹{v['total_amount']:>10,.2f}  {(v['narration'] or '')[:40]}{status}")


def view_balance(tree):
    """Show ledger balances."""
    query = input("  Search ledger name (or Enter for all): ").strip().lower()
    ledgers = tree.get_all_ledgers()
    if query:
        ledgers = [l for l in ledgers if query in l["name"].lower()]
    print(f"\n  {'Ledger':<35} {'Group':<25} {'Balance':>14}")
    print(f"  {'-'*35} {'-'*25} {'-'*14}")
    for l in ledgers:
        b = tree.get_ledger_balance(l["id"])
        if b["balance"] == 0:
            continue
        bal_str = f"₹{b['balance']:>10,.2f} {b['type']}"
        print(f"  {l['name']:<35} {l['group_name']:<25} {bal_str:>14}")


def add_ledger_interactive(tree):
    """Add a new ledger account."""
    ledgers = tree.get_all_ledgers()
    groups  = list({l["group_name"] for l in ledgers})
    groups.sort()

    print("\n  Available groups:")
    for i, g in enumerate(groups, 1):
        print(f"    [{i:>2}] {g}")

    try:
        gidx  = int(input("\n  Choose group number: ")) - 1
        gname = groups[gidx]
    except (ValueError, IndexError):
        print("  Invalid choice.")
        return

    name = input("  Ledger name         : ").strip()
    if not name:
        return

    kwargs = {}
    if "Bank" in gname:
        kwargs["is_bank"]        = True
        kwargs["bank_name"]      = input("  Bank name           : ").strip()
        kwargs["account_number"] = input("  Account number      : ").strip()
        kwargs["ifsc"]           = input("  IFSC code           : ").strip()

    ob = input("  Opening balance (₹) [0]: ").strip()
    if ob:
        kwargs["opening_balance"] = float(ob)
        otype = input("  Opening type Dr/Cr  [Dr]: ").strip() or "Dr"
        kwargs["opening_type"] = otype

    gstin = input("  GSTIN (optional)    : ").strip()
    if gstin:
        kwargs["gstin"] = gstin
        kwargs["state_code"] = gstin[:2]

    pan = input("  PAN (optional)      : ").strip()
    if pan:
        kwargs["pan"] = pan

    tds = input("  TDS applicable? y/n [n]: ").strip().lower()
    if tds == "y":
        kwargs["is_tds_applicable"] = True
        print("  Sections: 194C 194H 194I 194J 194A")
        kwargs["tds_section"] = input("  TDS section         : ").strip()
        kwargs["tds_rate"]    = float(input("  TDS rate %          : ") or 10)

    lid = tree.add_ledger(name, gname, **kwargs)
    print(f"\n  ✓ Ledger '{name}' created (id={lid})")


def main():
    print("\n" + "="*55)
    print("  ACCOUNTING SYSTEM  v1.0")
    print("  Python + SQLite  |  Indian GST + TDS")
    print("="*55)

    # Load or create company
    db, company_id, tree = load_company()
    if db is None:
        print("\n  No companies found. Let's create one.")
        db, company_id, tree = setup_company()

    engine = VoucherEngine(db, company_id, user_id=None)

    # Get company name
    row = db.execute("SELECT name FROM companies WHERE id=?", (company_id,)).fetchone()
    cname = row["name"] if row else "Company"

    while True:
        print(f"\n  [{cname}]  What would you like to do?")
        print("  [1] Post a voucher")
        print("  [2] View Day Book")
        print("  [3] View ledger balances")
        print("  [4] Add a new ledger account")
        print("  [5] Switch / create company")
        print("  [0] Exit")

        choice = input("\n  Enter choice: ").strip()

        if choice == "1":
            post_voucher_interactive(engine, tree)
        elif choice == "2":
            view_daybook(engine)
        elif choice == "3":
            view_balance(tree)
        elif choice == "4":
            add_ledger_interactive(tree)
        elif choice == "5":
            db.close()
            db, company_id, tree = load_company()
            if db is None:
                db, company_id, tree = setup_company()
            engine = VoucherEngine(db, company_id)
            row = db.execute("SELECT name FROM companies WHERE id=?", (company_id,)).fetchone()
            cname = row["name"] if row else "Company"
        elif choice == "0":
            print("\n  Goodbye!\n")
            db.close()
            break
        else:
            print("  Invalid choice.")


if __name__ == "__main__":
    main()
