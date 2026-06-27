# -*- coding: utf-8 -*-
"""Render the Home dashboard (tile menu) + Bank Reconciliation as WEB UI,
pulling live data from core (Sunrise Traders), then screenshot both."""
import sys, os, calendar
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.models import Database
from core.account_tree import AccountTree

SLUG = "sunrise_traders"
OUT = os.path.dirname(os.path.abspath(__file__))
db = Database(SLUG); db.connect()
cid = db.execute("SELECT id FROM companies LIMIT 1").fetchone()["id"]
cname = db.execute("SELECT name FROM companies WHERE id=?", (cid,)).fetchone()["name"]
tree = AccountTree(db, cid)


def fmt(a):
    sym = "₹"; sign = "-" if a < 0 else ""; n = abs(int(round(a)))
    if n >= 10_000_000: return f"{sign}{sym} {n/10_000_000:.2f} Cr"
    if n >= 100_000:    return f"{sign}{sym} {n/100_000:.2f} L"
    return f"{sign}{sym} {n:,}"


def cash_bank():
    try:
        ids = [r["id"] for r in tree.get_bank_cash_ledgers()]
        bals = tree.get_all_ledger_balances(); tot = 0.0
        for i in ids:
            b = bals.get(i)
            if b: tot += b["balance"] if b["type"] == "Dr" else -b["balance"]
        return tot
    except Exception: return 0.0


def group_total(name, side):
    try:
        rows = db.execute(
            "SELECT l.id FROM ledgers l JOIN account_groups g ON l.group_id=g.id "
            "WHERE l.company_id=? AND g.name=?", (cid, name)).fetchall()
        bals = tree.get_all_ledger_balances(); tot = 0.0
        for r in rows:
            b = bals.get(r["id"])
            if b: tot += b["balance"] if b["type"] == side else -b["balance"]
        return tot
    except Exception: return 0.0


def inc_exp(s, e):
    try:
        r = db.execute(
            "SELECT COALESCE(SUM(CASE WHEN g.nature='INCOME' THEN vl.cr_amount-vl.dr_amount ELSE 0 END),0) inc,"
            " COALESCE(SUM(CASE WHEN g.nature='EXPENSE' THEN vl.dr_amount-vl.cr_amount ELSE 0 END),0) exp "
            "FROM voucher_lines vl JOIN vouchers v ON vl.voucher_id=v.id "
            "JOIN ledgers l ON vl.ledger_id=l.id JOIN account_groups g ON l.group_id=g.id "
            "WHERE v.company_id=? AND v.is_cancelled=0 AND v.voucher_date>=? AND v.voucher_date<=?",
            (cid, s, e)).fetchone()
        return float(r["inc"] or 0), float(r["exp"] or 0)
    except Exception: return 0.0, 0.0


def month_ranges():
    t = date.today(); d = t.day
    def md(y, m):
        last = calendar.monthrange(y, m)[1]
        return date(y, m, 1).isoformat(), date(y, m, min(d, last)).isoformat()
    cur = (t.replace(day=1).isoformat(), t.isoformat())
    ly, lm = (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)
    return cur, md(ly, lm), md(t.year - 1, t.month)


def recent():
    try:
        return [dict(r) for r in db.execute(
            "SELECT voucher_date,voucher_type,voucher_number,narration,total_amount "
            "FROM vouchers WHERE company_id=? AND is_cancelled=0 "
            "ORDER BY voucher_date DESC,id DESC LIMIT 8", (cid,)).fetchall()]
    except Exception: return []


def risks():
    out = []; today = date.today().isoformat()
    cur, _, _ = month_ranges(); i, e = inc_exp(*cur)
    if e > i + 0.01:
        out.append(("bad", f"Spending is ahead of income this month by {fmt(e-i)}"))
    try:
        from core.reports_engine import ReportsEngine
        re = ReportsEngine(db, cid)
        rec = re.receivables_aging(today); r90 = rec.get("totals", {}).get("b90p", 0.0)
        if r90 > 0.01:
            top = rec["rows"][0]["ledger"] if rec.get("rows") else ""
            out.append(("warn", f"{fmt(r90)} receivable overdue beyond 90 days" + (f" — {top} the largest" if top else "")))
        pay = re.payables_aging(today); p90 = pay.get("totals", {}).get("b90p", 0.0)
        if p90 > 0.01:
            top = pay["rows"][0]["ledger"] if pay.get("rows") else ""
            out.append(("warn", f"{fmt(p90)} payable overdue beyond 90 days" + (f" — {top} the largest" if top else "")))
    except Exception: pass
    return out


CSS = """
:root{--bg:#F1F4F9;--card:#FFFFFF;--card2:#F8FAFC;--accent:#0EA5A5;--accent-soft:#E0F4F3;
--text:#0F172A;--sec:#5A6B8B;--dim:#94A3B8;--border:#E5E9F1;--border2:#D8DDE6;
--good:#057A55;--good-soft:#EAF7EF;--good-bg:#D9F5E6;--warn:#B45309;--warn-soft:#FCF1DC;--warn-bg:#FDEBD0;
--bad:#C83A3A;--bad-soft:#FCEAEA;--bad-bg:#FBE1E1;--info:#1849A9;--info-bg:#D8E5FC;}
*{box-sizing:border-box;font-family:'Segoe UI','Inter',system-ui,sans-serif;}
body{margin:0;background:var(--bg);color:var(--text);font-size:13px;}
.app{display:flex;min-height:100vh;}
.sidebar{width:220px;flex:0 0 220px;background:#fff;border-right:1px solid var(--border);}
.logo{padding:20px 18px 14px;border-bottom:1px solid var(--border);font-weight:800;font-size:22px;letter-spacing:-.02em;}
.logo .b{color:var(--accent);}
.company{font-size:11px;color:var(--sec);padding:10px 18px 2px;font-weight:600;}
.nav-sec{color:var(--dim);font-size:10px;letter-spacing:1.5px;padding:16px 22px 5px;font-weight:700;}
.nav-item{padding:9px 22px;font-size:13px;color:var(--sec);border-left:3px solid transparent;}
.nav-item.active{color:var(--accent);background:var(--accent-soft);border-left:3px solid var(--accent);font-weight:600;}
.main{flex:1;}
.ptitle{font-size:22px;font-weight:800;padding:22px 26px 2px;letter-spacing:-.02em;}
.psub{font-size:12px;color:var(--sec);padding:0 26px 16px;}
.content{padding:0 26px 26px;}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px;}
.tile{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 14px;}
.tile.good{background:var(--good-soft);border-color:var(--good);}
.tile.warn{background:var(--warn-soft);border-color:var(--warn);}
.tile.bad{background:var(--bad-soft);border-color:var(--bad);}
.tile .lbl{font-size:10px;font-weight:700;color:var(--sec);letter-spacing:.08em;text-transform:uppercase;}
.tile .val{font-size:21px;font-weight:700;margin-top:5px;letter-spacing:-.02em;}
.tile.good .val{color:var(--good);}.tile.warn .val{color:var(--warn);}.tile.bad .val{color:var(--bad);}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:18px;}
.sec-lbl{color:var(--sec);font-size:10px;font-weight:700;letter-spacing:1px;margin:6px 0 8px;}
.panel{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;}
table.cmp{width:100%;border-collapse:collapse;}
table.cmp th{color:var(--dim);font-size:10px;font-weight:700;text-align:right;padding:4px 6px;letter-spacing:.5px;}
table.cmp td{font-size:13px;padding:6px 6px;text-align:right;}
table.cmp td.name{text-align:left;color:var(--sec);font-weight:600;}
.up{color:var(--good);font-size:11px;}.down{color:var(--bad);font-size:11px;}
.risk{display:flex;align-items:center;gap:10px;background:#EEF2F7;border:1px solid var(--border);border-radius:8px;padding:9px 12px;margin-bottom:6px;}
.risk .ic{font-weight:700;width:16px;}
.risk.bad{border-left:3px solid var(--bad);}.risk.bad .ic{color:var(--bad);}
.risk.warn{border-left:3px solid var(--warn);}.risk.warn .ic{color:var(--warn);}
.risk.good{border-left:3px solid var(--good);}.risk.good .ic{color:var(--good);}
.risk .chev{margin-left:auto;color:var(--dim);font-size:16px;font-weight:700;}
.act-row{display:flex;align-items:center;gap:10px;padding:9px 2px;border-bottom:1px solid var(--border);}
.act-row .d{width:96px;color:var(--sec);}.act-row .r{width:150px;font-weight:600;}
.act-row .n{flex:1;color:var(--sec);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.act-row .a{font-weight:600;text-align:right;}
.qa{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;}
.qa .card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px 14px;}
.qa .card:hover{border-color:var(--accent);}
.qa .t{font-weight:700;font-size:13px;}.qa .s{font-size:10px;color:var(--sec);margin-top:2px;}
/* tabs + tables */
.tabs{display:flex;gap:0;border-bottom:1px solid var(--border);margin:4px 0 0;}
.tab{padding:9px 20px;color:var(--sec);font-size:13px;border-bottom:2px solid transparent;cursor:pointer;}
.tab.active{color:var(--accent);border-bottom:2px solid var(--accent);font-weight:700;}
.toolbar{display:flex;align-items:center;gap:8px;margin:12px 0 8px;}
.search{flex:1;max-width:380px;background:var(--card2);border:1px solid var(--border);border-radius:8px;padding:6px 12px;color:var(--sec);font-size:12px;}
.btn{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:5px 12px;font-size:12px;color:var(--text);}
.btn.primary{background:var(--accent);color:#fff;border:none;font-weight:700;}
.grid{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden;}
.grid th{background:var(--card2);color:var(--sec);font-size:11px;font-weight:700;letter-spacing:.5px;text-align:left;padding:9px 12px;border-bottom:1px solid var(--border);}
.grid td{padding:8px 12px;border-bottom:1px solid var(--border);font-size:12.5px;}
.grid tr:nth-child(even) td{background:var(--card2);}
.grid td.num{text-align:right;font-variant-numeric:tabular-nums;}
.pill{font-size:10px;font-weight:700;border-radius:9px;padding:2px 9px;}
.pill.cr{background:var(--good-bg);color:var(--good);}.pill.dr{background:var(--bad-bg);color:var(--bad);}
.pill.warn{background:var(--warn-bg);color:var(--warn);}
.adrop{background:var(--card2);border:1px solid var(--border);border-radius:5px;padding:3px 10px;font-size:11px;color:var(--text);}
.bar{display:flex;align-items:center;gap:8px;margin-bottom:8px;}
.bar .sum{color:var(--sec);font-size:11px;flex:1;}
"""

NAV = """
<div class="sidebar">
  <div class="logo">books<span class="b">HQ</span></div>
  <div class="company">{cname}</div>
  <div class="nav-sec">ACCOUNTING</div>
  <div class="nav-item {h}">Home</div>
  <div class="nav-item">Post Voucher</div>
  <div class="nav-item">Day Book</div>
  <div class="nav-item">Ledger Balances</div>
  <div class="nav-sec">BANKING</div>
  <div class="nav-item {b}">Bank Reconciliation</div>
  <div class="nav-item">AI Documents Inbox</div>
  <div class="nav-sec">REPORTS</div>
  <div class="nav-item">Trial Balance</div>
  <div class="nav-item">Profit &amp; Loss</div>
  <div class="nav-item">GST Filing</div>
</div>"""


def shell(title, sub, body, active):
    nav = NAV.format(cname=cname, h="active" if active == "home" else "",
                     b="active" if active == "bank" else "")
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head>"
            f"<body><div class='app'>{nav}<div class='main'>"
            f"<div class='ptitle'>{title}</div><div class='psub'>{sub}</div>"
            f"<div class='content'>{body}</div></div></div></body></html>")


# ───────────────────────── Dashboard (tile menu) ─────────────────────────
cash = cash_bank(); recv = group_total("Sundry Debtors", "Dr"); pay = group_total("Sundry Creditors", "Cr")
cur, lm, ly = month_ranges(); ic, ec = inc_exp(*cur); il, el = inc_exp(*lm); iy, ey = inc_exp(*ly)
net = ic - ec
kpis = [("Cash & Bank", cash, "good" if cash >= 0 else "bad"),
        ("Receivables", recv, "warn" if recv > 0 else "good"),
        ("Payables", pay, "warn" if pay > 0 else "good"),
        ("Net this month", net, "good" if net >= 0 else "bad")]
kp_html = "".join(
    f"<div class='tile {s}'><div class='lbl'>{l}</div><div class='val'>{fmt(v)}</div></div>"
    for l, v, s in kpis)


def delta(now, base, hib):
    if abs(base) < 0.01: return ""
    pct = (now - base) / abs(base) * 100; up = pct >= 0
    good = up if hib else not up
    return f" <span class='{'up' if good else 'down'}'>{'▲' if up else '▼'}{abs(pct):.0f}%</span>"


cmp_rows = [("Income", ic, iy, il, True), ("Expenses", ec, ey, el, False), ("Net", net, iy - ey, il - el, True)]
cmp_html = "<table class='cmp'><tr><th></th><th>THIS MONTH</th><th>SAME MO. LAST YR</th><th>LAST MONTH</th></tr>"
for nm, c, y, l, hib in cmp_rows:
    cmp_html += (f"<tr><td class='name'>{nm}</td><td><b>{fmt(c)}</b></td>"
                 f"<td>{fmt(y)}{delta(c,y,hib)}</td><td>{fmt(l)}{delta(c,l,hib)}</td></tr>")
cmp_html += "</table>"

rk = risks()
if rk:
    rk_html = "".join(f"<div class='risk {s}'><span class='ic'>⚠</span><span>{t}</span><span class='chev'>›</span></div>" for s, t in rk)
else:
    rk_html = "<div class='risk good'><span class='ic'>✓</span><span>Nothing needs attention — the books look healthy.</span></div>"

rec_html = ""
for v in recent():
    rec_html += (f"<div class='act-row'><span class='d'>{v.get('voucher_date','')}</span>"
                 f"<span class='r'>{v.get('voucher_type','')} {v.get('voucher_number','')}</span>"
                 f"<span class='n'>{(v.get('narration') or '').strip()}</span>"
                 f"<span class='a'>{fmt(v.get('total_amount') or 0)}</span></div>")

qa = [("Post Voucher", "Record a new entry", "✏"), ("Day Book", "Browse all vouchers", "\U0001f4cb"),
      ("Reports", "Trial balance, P&amp;L and more", "\U0001f4ca"), ("Documents Inbox", "AI-read incoming documents", "\U0001f4e5")]
qa_html = "".join(f"<div class='card'><div class='t'>{i} {t}</div><div class='s'>{s}</div></div>" for t, s, i in qa)

dash_body = (
    f"<div class='kpis'>{kp_html}</div>"
    f"<div class='cols'><div><div class='sec-lbl'>INCOME &amp; EXPENSE</div><div class='panel'>{cmp_html}</div></div>"
    f"<div><div class='sec-lbl'>NEEDS ATTENTION</div>{rk_html}</div></div>"
    f"<div class='sec-lbl'>RECENT ACTIVITY</div><div class='panel' style='padding:4px 16px'>{rec_html}</div>"
    f"<div class='sec-lbl' style='margin-top:18px'>QUICK ACTIONS</div><div class='qa'>{qa_html}</div>")

from datetime import date as _d
sub = f"Books HQ &nbsp;·&nbsp; {_d.today().strftime('%A, %d %B %Y')}"
open(os.path.join(OUT, "_dash.html"), "w", encoding="utf-8").write(shell(cname, sub, dash_body, "home"))


# ───────────────────────── Bank Reconciliation (review) ─────────────────────────
# Real screen structure; representative statement lines for the demo.
brk = [("Matched", "47", "good"), ("Unmatched · stmt", "12", "warn"),
       ("Unmatched · book", "5", "warn"), ("Ignored", "3", "")]
brk_html = "".join(f"<div class='tile {s}'><div class='lbl'>{l}</div><div class='val'>{v}</div></div>" for l, v, s in brk)

unmatched = [
    ("02 Jun 2026", "CR", "₹ 45,000", "NEFT IN NOVA DISTRIBUTORS", "N06021457", "warn"),
    ("03 Jun 2026", "DR", "₹ 1,180", "UPI/JIO RECHARGE/PYTM", "UPI440231", "warn"),
    ("05 Jun 2026", "DR", "₹ 12,500", "AMAZON SELLER FEES", "AMZ-9921", "warn"),
    ("07 Jun 2026", "CR", "₹ 88,400", "RTGS SUNDARAM PACKAGING", "R0706884", "warn"),
    ("09 Jun 2026", "DR", "₹ 6,750", "ELECTRICITY BILL BSES", "BSES06", "warn"),
    ("11 Jun 2026", "DR", "₹ 25,000", "UPI/RENT/LANDLORD", "UPI553120", "warn"),
    ("12 Jun 2026", "CR", "₹ 1,20,000", "IMPS METRO RETAIL", "I07121200", "warn"),
    ("14 Jun 2026", "DR", "₹ 3,299", "AIRTEL BROADBAND", "AIR0614", "warn"),
]
um_rows = "".join(
    f"<tr><td>{d}</td><td><span class='pill {'cr' if sg=='CR' else 'dr'}'>{sg}</span></td>"
    f"<td class='num'>{amt}</td><td>{nar}</td><td>{ref}</td>"
    f"<td><span class='pill warn'>Unmatched</span></td>"
    f"<td><span class='adrop'>Actions ▾</span></td></tr>"
    for d, sg, amt, nar, ref, st in unmatched)

bank_body = (
    f"<div class='kpis'>{brk_html}</div>"
    "<div class='bar'><span class='btn'>← Setup</span>"
    "<span class='sum'>HDFC Bank · 01 Jun → 30 Jun 2026 · 67 statement lines · 47 matched automatically</span>"
    "<span class='btn primary'>Continue to Summary →</span></div>"
    "<div class='tabs'><div class='tab'>Matched</div><div class='tab active'>Unmatched Statement</div>"
    "<div class='tab'>Unmatched Book</div><div class='tab'>Ignored</div></div>"
    "<div class='toolbar'><span class='search'>\U0001f50d Filter narration / reference — e.g. JIO, AMAZON…</span>"
    "<span class='btn'>Select all visible</span></div>"
    "<table class='grid'><tr><th>Date</th><th>Sign</th><th style='text-align:right'>Amount</th>"
    "<th>Narration</th><th>Reference</th><th>Status</th><th></th></tr>"
    f"{um_rows}</table>")

open(os.path.join(OUT, "_bank.html"), "w", encoding="utf-8").write(
    shell("Bank Reconciliation", "Match imported bank statements to your ledger entries.", bank_body, "bank"))

print("HTML written. cash=%s recv=%s pay=%s net=%s risks=%d recent=%d"
      % (fmt(cash), fmt(recv), fmt(pay), fmt(net), len(rk), len(recent())))

# ───────────────────────── Screenshot both ─────────────────────────
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1380, "height": 900})
    for name in ("_dash", "_bank"):
        pg.goto("file:///" + os.path.join(OUT, name + ".html").replace("\\", "/"))
        pg.wait_for_timeout(400)
        pg.screenshot(path=os.path.join(OUT, name + ".png"), full_page=True)
    b.close()
print("screenshots saved:", os.path.join(OUT, "_dash.png"), os.path.join(OUT, "_bank.png"))
