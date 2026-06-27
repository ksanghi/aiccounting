# -*- coding: utf-8 -*-
"""Element-diff tool: enumerate every control on each DESKTOP page (Qt widget
tree) vs the matching WEB page (rendered DOM), and report what the web is
missing. Removes human eyeballing from the comparison.

Run:  python _element_diff.py      (web server must be live on :8800)
"""
import os, sys, re, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PySide6.QtWidgets import (QApplication, QPushButton, QCheckBox, QComboBox,
                               QLineEdit, QTableWidget, QLabel, QWidget)
from core.models import Database
from core.account_tree import AccountTree
from core.voucher_engine import VoucherEngine
from ui.theme import set_theme_mode

app = QApplication([])
set_theme_mode("light")
db = Database("sunrise_traders"); db.connect()
cid = db.execute("SELECT id FROM companies LIMIT 1").fetchone()["id"]
tree = AccountTree(db, cid)
engine = VoucherEngine(db, cid)

ROUTE = {
    "Home": "/dashboard", "Dashboard": "/dashboard", "Post Voucher": "/post-voucher",
    "Day Book": "/daybook", "Ledger Balances": "/ledgers", "Trial Balance": "/trial-balance",
    "Profit & Loss": "/pnl", "P & L": "/pnl", "Balance Sheet": "/balance-sheet",
    "Cash Book": "/cash-book", "Bank Book": "/bank-book", "Ledger Account": "/ledger/1",
    "Receipts & Payments": "/receipts-payments", "Rcpts & Pmts": "/receipts-payments",
    "TDS Reports": "/tds", "TDS Register": "/tds", "Receivables Aging": "/aging-receivable",
    "Payables Aging": "/aging-payable", "Bank Reconciliation": "/bankreco",
    "Ledger Reconciliation": "/ledger-reco", "Bill-wise Outstanding": "/bill-wise",
    "Cash-Flow Planning": "/cash-flow", "GST Returns": "/gst", "TDS Report": "/tds",
    "1099 Contractors": "/form-1099", "Schedule C": "/schedule-c", "Mileage Log": "/mileage",
    "Company Settings": "/company-settings", "Settings": "/company-settings",
    "Users": "/users", "License & Plan": "/license", "AI Credits": "/ai-credits",
    "Backup & Restore": "/backup", "Backup": "/backup", "Migration": "/migration",
    "Period Locks": "/period-locks", "Feedback": "/feedback", "User Manual": "/manual",
    "AI Documents Inbox": "/documents", "Verbal Entry": "/verbal",
}


def dctrls(w):
    btns = sorted({b.text().strip() for b in w.findChildren(QPushButton) if b.text().strip()})
    checks = sorted({c.text().strip() for c in w.findChildren(QCheckBox) if c.text().strip()})
    ph = sorted({e.placeholderText().strip() for e in w.findChildren(QLineEdit) if e.placeholderText().strip()})
    combos = len([c for c in w.findChildren(QComboBox)])
    headers = []
    for t in w.findChildren(QTableWidget):
        for i in range(t.columnCount()):
            it = t.horizontalHeaderItem(i)
            if it and it.text().strip():
                headers.append(it.text().strip())
    kpi = []
    for x in w.findChildren(QWidget):
        if type(x).__name__ == "KPITile":
            for l in x.findChildren(QLabel):
                tx = l.text().strip()
                if tx and len(tx) > 2 and not tx[0].isdigit():
                    kpi.append(tx)
    return {"buttons": btns, "checks": checks, "placeholders": ph,
            "combos": combos, "headers": sorted(set(headers)), "kpi": sorted(set(kpi))}


desktop = {}
try:
    from ui.main_window import MainWindow
    mw = MainWindow(db, cid, tree, engine)
    app.processEvents()
    for (label, icon, widget, btn) in mw._pages:
        try:
            desktop[label] = dctrls(widget)
        except Exception as e:
            desktop[label] = {"error": str(e)}
    print("desktop pages found:", len(desktop))
    print("UNMAPPED labels (no web route):", [l for l in desktop if l not in ROUTE])
except Exception as e:
    print("MainWindow build FAILED:", repr(e))
    sys.exit(1)


def wctrls(html):
    strip = lambda s: re.sub("<[^>]+>", "", s)
    btns = {strip(b).strip() for b in re.findall(r"<button[^>]*>(.*?)</button>", html, re.S)}
    links = {strip(a).strip() for a in re.findall(r"<a [^>]*>(.*?)</a>", html, re.S)}
    headers = {strip(h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", html, re.S)}
    ph = set(re.findall(r"placeholder=['\"]([^'\"]*)['\"]", html))
    opts = {strip(o).strip() for o in re.findall(r"<option[^>]*>(.*?)</option>", html, re.S)}
    selects = len(re.findall(r"<select", html))
    import html as _h
    textnorm = re.sub(r"[^a-z0-9]", "", _h.unescape(re.sub("<[^>]+>", " ", html)).lower())
    return {"buttons": {b for b in btns if b}, "links": {a for a in links if a},
            "headers": {h for h in headers if h}, "ph": ph, "opts": opts, "selects": selects, "textnorm": textnorm}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def present(ctrl, wc):
    n = norm(ctrl)
    if len(n) < 2:
        return True
    pool = wc["buttons"] | wc["links"] | wc["headers"] | wc["ph"] | wc["opts"]
    for p in pool:
        pn = norm(p)
        if pn and (n in pn or pn in n):
            return True
    return False


from playwright.sync_api import sync_playwright  # noqa: E402
B = "http://127.0.0.1:8800"
report = {}
with sync_playwright() as pw:
    br = pw.chromium.launch(); pg = br.new_page(viewport={"width": 1320, "height": 900})
    for label, dc in desktop.items():
        route = ROUTE.get(label)
        if not route or "error" in dc:
            continue
        try:
            pg.goto(B + route, wait_until="load", timeout=15000); pg.wait_for_timeout(450)
            html = pg.content()
        except Exception as e:
            report[label] = {"route": route, "web_error": str(e)[:80]}
            continue
        wc = wctrls(html)
        miss = {}
        mb = [b for b in dc["buttons"] if not present(b, wc)]
        mc = [c for c in dc["checks"] if not present(c, wc)]
        mh = [h for h in dc["headers"] if not present(h, wc)]
        mk = [k for k in dc["kpi"] if len(norm(k)) >= 3 and norm(k) not in wc.get("textnorm", "")]
        cg = max(0, dc["combos"] - wc["selects"])
        if mb: miss["missing_buttons"] = mb
        if mc: miss["missing_checkboxes"] = mc
        if mh: miss["missing_columns"] = mh
        if mk: miss["missing_kpi_tiles"] = mk
        if cg: miss["missing_dropdowns"] = cg
        if miss:
            miss["route"] = route
            report[label] = miss
    br.close()

print("\n================ ELEMENT GAPS (web missing vs desktop) ================")
if not report:
    print("No gaps found.")
for label, r in report.items():
    print(f"\n## {label}   [{r.get('route', r.get('web_error',''))}]")
    for k in ("missing_buttons", "missing_checkboxes", "missing_columns", "missing_kpi_tiles", "missing_dropdowns"):
        if r.get(k):
            print(f"   - {k}: {r[k]}")
json.dump(report, open("_element_gaps.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n(saved _element_gaps.json)")
