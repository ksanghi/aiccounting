"""
Daily-progress dashboard — Sales / Marketing / Operations (v2).

GET /admin/dashboard?token=ADMIN_TOKEN
  &days=N        period preset (1=today IST, 7, 30, 90, 365, 0=all). Default 30.
  &view=NAME     drill-down detail table: orders | leads | installs | licences | contacts
  &format=csv    (with view=contacts) download the contacts list as CSV

Read-only; all data from existing license-server tables. Tables are sortable
(click a header) and filterable (type in the box). The admin token is carried
across links by a tiny JS shim so you never re-paste it.
"""
from __future__ import annotations

import csv
import datetime as dt
import html as _html
import io

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from license_server.models import (
    License, Install, Order, ValidationLog, Credit, CreditTopup,
    AIUsageLog, MachineBinding, ChatLearned,
)

IST = dt.timedelta(hours=5, minutes=30)
PRESETS = [(1, "Today"), (7, "7 days"), (30, "30 days"),
           (90, "90 days"), (365, "1 year"), (0, "All time")]


def _rupees(paise) -> str:
    return f"₹{(int(paise or 0) / 100):,.0f}"


def _since(days: int):
    """UTC datetime threshold for the period, or None for all-time."""
    now = dt.datetime.utcnow()
    if days == 1:
        today_ist = (now + IST).date()
        return dt.datetime.combine(today_ist, dt.time.min) - IST
    if not days or days <= 0:
        return None
    return now - dt.timedelta(days=days)


def _period_label(days: int) -> str:
    for d, lbl in PRESETS:
        if d == days:
            return lbl
    return f"Last {days} days"


def _scalar(db, stmt) -> int:
    return int(db.scalar(stmt) or 0)


# ── internal / test exclusion ────────────────────────────────────────────────
# Keep the funnel honest: our own testing, family accounts, and obvious junk
# are dropped from every metric + drill-down so the numbers reflect real
# prospects only. One source of truth, used by both the SQL counts
# (_not_internal) and the Python row views (is_internal). Add a new tester here
# and it disappears from the whole dashboard at once.
_INTERNAL_EMAILS = {
    "krishan.sanghi@gmail.com",
    "aashray.sanghi@gmail.com",
    "info@ai-consultants.in",
}
_INTERNAL_DOMAINS = {"example.com", "test.com", "accgenie.in",
                     "ai-consultants.in", "abc"}
_INTERNAL_PREFIXES = ("test", "smoketest")   # localpart starts-with


def is_internal(email) -> bool:
    """True for our own/test/junk addresses (and anything not a real email)."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return True                          # blank / junk → not a prospect
    local, _, dom = e.partition("@")
    if e in _INTERNAL_EMAILS or dom in _INTERNAL_DOMAINS:
        return True
    return any(local.startswith(p) for p in _INTERNAL_PREFIXES)


def _not_internal(col):
    """SQLAlchemy condition mirroring is_internal(), for aggregate counts."""
    c = func.lower(func.trim(func.coalesce(col, "")))
    conds = [c.like("%@%")]
    conds += [c != e for e in _INTERNAL_EMAILS]
    conds += [c.notlike(f"%@{d}") for d in _INTERNAL_DOMAINS]
    conds += [c.notlike(f"{p}%") for p in _INTERNAL_PREFIXES]
    return and_(*conds)


# ── shared chrome ────────────────────────────────────────────────────────────
CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#0b1220;color:#e6edf6;margin:0;padding:16px 20px 50px;}
a{color:#8ab4ff;text-decoration:none;} a:hover{text-decoration:underline;}
h1{font-size:20px;margin:0 0 2px;} .gen{color:#8aa0bd;font-size:12px;margin-bottom:14px;}
h2{font-size:13px;letter-spacing:.6px;text-transform:uppercase;color:#fcd34d;margin:24px 0 10px;border-bottom:1px solid #1e2a3f;padding-bottom:6px;}
.periods{margin:6px 0 16px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;}
.periods a,.periods span.sel{padding:5px 12px;border:1px solid #1e2a3f;border-radius:18px;font-size:12.5px;color:#cdd9ee;background:#111a2e;}
.periods span.sel{background:#fcd34d;color:#0f1629;border-color:#fcd34d;font-weight:700;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;}
.c{background:#111a2e;border:1px solid #1e2a3f;border-radius:12px;padding:13px 15px;display:block;color:inherit;}
a.c:hover{border-color:#fcd34d;text-decoration:none;}
.c .t{color:#8aa0bd;font-size:12px;} .c .v{font-size:25px;font-weight:800;margin:3px 0;}
.c .s{color:#6b7f9c;font-size:11px;} .c .dd{color:#8ab4ff;font-size:10.5px;margin-top:5px;}
table{width:100%;border-collapse:collapse;margin:8px 0 4px;font-size:12.5px;background:#0e1626;border:1px solid #1e2a3f;border-radius:10px;overflow:hidden;}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid #18243a;} th{background:#13203a;color:#9fb3d1;font-weight:600;cursor:pointer;user-select:none;}
th:hover{color:#fcd34d;} td.empty{color:#6b7f9c;text-align:center;}
.sf-filter{margin:6px 0;padding:7px 11px;width:280px;max-width:100%;background:#0e1626;border:1px solid #1e2a3f;border-radius:8px;color:#e6edf6;font-size:12.5px;}
.h3{font-size:12px;color:#9fb3d1;margin:14px 0 0;} .two{display:grid;grid-template-columns:1fr 1fr;gap:18px;}
@media(max-width:760px){.two{grid-template-columns:1fr;}}
.back{font-size:12.5px;} .btn{display:inline-block;padding:6px 13px;border:1px solid #1e2a3f;border-radius:8px;background:#13203a;color:#cdd9ee;font-size:12.5px;}
"""

JS = """
<script>
(function(){
  var tok=new URLSearchParams(location.search).get('token')||'';
  document.querySelectorAll('a[href^="?"], a[href^="/admin/"]').forEach(function(a){
    var u=new URL(a.getAttribute('href'), location.href);
    if(!u.searchParams.get('token')) u.searchParams.set('token',tok);
    a.setAttribute('href', u.pathname+u.search);
  });
  document.querySelectorAll('table.sf').forEach(function(t){
    var f=document.createElement('input'); f.className='sf-filter'; f.placeholder='filter…';
    t.parentNode.insertBefore(f,t);
    f.addEventListener('input',function(){
      var q=f.value.toLowerCase();
      Array.prototype.forEach.call(t.tBodies[0].rows,function(r){
        r.style.display=r.textContent.toLowerCase().indexOf(q)>=0?'':'none';});
    });
    Array.prototype.forEach.call(t.tHead.rows[0].cells,function(th,i){
      th.addEventListener('click',function(){
        var rows=Array.prototype.slice.call(t.tBodies[0].rows);
        var asc=th.getAttribute('data-asc')!=='1'; th.setAttribute('data-asc',asc?'1':'0');
        rows.sort(function(a,b){
          var x=a.cells[i].getAttribute('data-sort')||a.cells[i].textContent;
          var y=b.cells[i].getAttribute('data-sort')||b.cells[i].textContent;
          var nx=parseFloat(String(x).replace(/[^0-9.\\-]/g,'')), ny=parseFloat(String(y).replace(/[^0-9.\\-]/g,''));
          if(!isNaN(nx)&&!isNaN(ny)) return asc?nx-ny:ny-nx;
          return asc?String(x).localeCompare(y):String(y).localeCompare(x);
        });
        rows.forEach(function(r){t.tBodies[0].appendChild(r);});
      });
    });
  });
})();
</script>
"""


def _periods_bar(days: int, view: str) -> str:
    out = ['<div class="periods"><span style="color:#8aa0bd;font-size:12px">Period:</span>']
    for d, lbl in PRESETS:
        if d == days:
            out.append(f'<span class="sel">{lbl}</span>')
        else:
            v = f"&view={_html.escape(view)}" if view else ""
            out.append(f'<a href="?days={d}{v}">{lbl}</a>')
    out.append("</div>")
    return "".join(out)


def _table(headers, rows, sf=True) -> str:
    """rows = list of tuples; a cell may be (display, sortkey) for typed sort."""
    h = "".join(f"<th>{_html.escape(str(x))}</th>" for x in headers)
    body = ""
    for r in rows:
        tds = ""
        for c in r:
            if isinstance(c, tuple):
                disp, sk = c
                tds += f'<td data-sort="{_html.escape(str(sk))}">{_html.escape(str(disp))}</td>'
            else:
                tds += f"<td>{_html.escape(str(c))}</td>"
        body += f"<tr>{tds}</tr>"
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="empty">— none in this period —</td></tr>'
    cls = ' class="sf"' if sf else ""
    return f"<table{cls}><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>"


def _shell(title: str, inner: str) -> str:
    gen = (dt.datetime.utcnow() + IST).strftime("%d %b %Y, %H:%M IST")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(title)}</title><style>{CSS}</style></head><body>
<h1>📊 {_html.escape(title)}</h1>
<div class="gen">Generated {gen} · all ₹ INR · our own/test accounts excluded · click a card to drill in · click a column to sort</div>
{inner}
<p style="margin-top:30px;color:#9ca3af;font-size:9.5px">© 2026 AI Consultants</p>
{JS}</body></html>"""


# ── overview ─────────────────────────────────────────────────────────────────
def _overview(db: Session, days: int) -> str:
    since = _since(days)
    today = (dt.datetime.utcnow() + IST).date()

    def n_orders(**w):
        q = select(func.count()).select_from(Order).where(
            _not_internal(Order.customer_email))
        if since is not None and w.get("by") == "created":
            q = q.where(Order.created_at >= since)
        if since is not None and w.get("by") == "paid":
            q = q.where(Order.updated_at >= since)
        if w.get("status"):
            q = q.where(Order.status == w["status"])
        return _scalar(db, q)

    rev = select(func.coalesce(func.sum(Order.amount_paise), 0)).where(
        Order.status == "paid", Order.currency == "INR",
        _not_internal(Order.customer_email))
    if since is not None:
        rev = rev.where(Order.updated_at >= since)
    revenue = _scalar(db, rev)

    created = n_orders(by="created")
    paid = n_orders(by="paid", status="paid")
    conv = f"{(100*paid/created):.0f}%" if created else "—"

    lic_q = select(func.count()).select_from(License).where(
        _not_internal(License.customer_email))
    if since is not None:
        lic_q = lic_q.where(License.created_at >= since)
    new_lic = _scalar(db, lic_q)
    active_lic = _scalar(db, select(func.count()).select_from(License)
                         .where(License.revoked == False, License.expires_at >= today,
                                _not_internal(License.customer_email)))  # noqa:E712

    inst_q = select(func.count()).select_from(Install)
    if since is not None:
        inst_q = inst_q.where(Install.first_seen_at >= since)
    new_inst = _scalar(db, inst_q)

    ai_q = select(func.coalesce(func.sum(AIUsageLog.paise_charged), 0))
    if since is not None:
        ai_q = ai_q.where(AIUsageLog.created_at >= since)
    ai_spend = _scalar(db, ai_q)
    wallet_out = _scalar(db, select(func.coalesce(func.sum(Credit.balance_paise), 0)))

    # lifetime (always all-time)
    life_rev = _scalar(db, select(func.coalesce(func.sum(Order.amount_paise), 0))
                       .where(Order.status == "paid", Order.currency == "INR",
                              _not_internal(Order.customer_email)))
    life_topups = _scalar(db, select(func.coalesce(func.sum(CreditTopup.amount_paise), 0))
                          .where(CreditTopup.source == "razorpay"))
    paying = _scalar(db, select(func.count(func.distinct(Order.customer_email)))
                     .where(Order.status == "paid",
                            _not_internal(Order.customer_email)))
    life_inst = _scalar(db, select(func.count()).select_from(Install))

    def card(title, value, sub="", drill="", href=""):
        link = href or (f"?days={days}&view={drill}" if drill else "")
        dd = '<div class="dd">View details →</div>' if link else ""
        body = (f'<div class="t">{_html.escape(title)}</div><div class="v">{value}</div>'
                f'<div class="s">{_html.escape(sub)}</div>{dd}')
        if link:
            return f'<a class="c" href="{link}">{body}</a>'
        return f'<div class="c">{body}</div>'

    lbl = _period_label(days)
    life = (card("Total revenue (lifetime)", _rupees(life_rev + life_topups),
                 f"sales {_rupees(life_rev)} + wallet {_rupees(life_topups)}", drill="orders")
            + card("Paying customers", f"{paying:,}", "all-time", drill="contacts")
            + card("Active licences", f"{active_lic:,}", "current", drill="licences")
            + card("Total installs", f"{life_inst:,}", "all-time", drill="installs"))

    sales = (card("Revenue", _rupees(revenue), lbl, drill="orders")
             + card("Orders paid", f"{paid:,}", f"{created} created · {conv} conv", drill="orders")
             + card("Abandoned checkouts", f"{n_orders(by='created', status='created'):,}",
                    "leads to follow up", drill="leads")
             + card("New licences", f"{new_lic:,}", lbl, drill="licences"))

    mk = (card("New installs", f"{new_inst:,}", lbl, drill="installs")
          + card("Chatbot questions",
                 f"{_scalar(db, select(func.count()).select_from(ChatLearned).where(ChatLearned.created_at >= since)) if since is not None else _scalar(db, select(func.count()).select_from(ChatLearned)):,}",
                 "review answers →", href="/admin/chat-review")
          + card("Contacts / audience", f"{_scalar(db, select(func.count(func.distinct(Order.customer_email))).where(Order.customer_email != '', _not_internal(Order.customer_email))):,}",
                 "emails captured", drill="contacts"))

    ops = (card("AI spend", _rupees(ai_spend), lbl, drill="aispend")
           + card("Wallet liability", _rupees(wallet_out), "unspent credits held",
                  drill="wallet")
           + card("Licence checks today",
                  f"{_scalar(db, select(func.count()).select_from(ValidationLog).where(ValidationLog.created_at >= _since(1))):,}",
                  "validations", drill="checks"))

    inner = (_periods_bar(days, "")
             + '<h2>🏆 Lifetime</h2><div class="grid">' + life + "</div>"
             + f'<h2>💰 Sales · {_html.escape(lbl)}</h2><div class="grid">' + sales + "</div>"
             + f'<h2>📣 Marketing · {_html.escape(lbl)}</h2><div class="grid">' + mk + "</div>"
             + f'<h2>⚙️ Operations · {_html.escape(lbl)}</h2><div class="grid">' + ops + "</div>")
    return _shell("AI Consultants — Dashboard", inner)


# ── drill-down detail views ──────────────────────────────────────────────────
def _fmt_dt(d):
    return d.strftime("%Y-%m-%d %H:%M") if d else ""


def _view(db: Session, view: str, days: int) -> str:
    since = _since(days)
    lbl = _period_label(days)
    back = '<p class="back"><a href="?days=' + str(days) + '">← Back to dashboard</a></p>'
    bar = _periods_bar(days, view)

    if view == "orders":
        q = select(Order).order_by(Order.created_at.desc())
        if since is not None:
            q = q.where(Order.created_at >= since)
        rows = []
        for o in db.scalars(q).all():
            if is_internal(o.customer_email):
                continue
            rows.append([_fmt_dt(o.created_at), o.customer_email or "—", o.product or "—",
                         o.plan or "—", o.kind or "—",
                         (_rupees(o.amount_paise), o.amount_paise or 0),
                         o.status or "—", o.razorpay_payment_id or ""])
        t = _table(["Created", "Email", "Product", "Plan", "Kind", "Amount", "Status", "Payment id"], rows)
        return _shell("Orders", bar + f"<h2>Orders · {_html.escape(lbl)} · {len(rows)}</h2>" + back + t)

    if view == "leads":
        q = (select(Order).where(Order.status == "created")
             .order_by(Order.created_at.desc()))
        if since is not None:
            q = q.where(Order.created_at >= since)
        rows = [[_fmt_dt(o.created_at), o.customer_email or "—", o.customer_name or "",
                 o.customer_phone or "", o.product or "—", o.plan or "—",
                 (_rupees(o.amount_paise), o.amount_paise or 0)]
                for o in db.scalars(q).all() if not is_internal(o.customer_email)]
        t = _table(["Created", "Email", "Name", "Phone", "Product", "Plan", "Amount"], rows)
        return _shell("Abandoned-checkout leads",
                      bar + f"<h2>Leads to follow up · {_html.escape(lbl)} · {len(rows)}</h2>" + back
                      + "<p style='color:#8aa0bd;font-size:12px'>Reached checkout, never paid — good outreach targets.</p>" + t)

    if view == "installs":
        q = select(Install).order_by(Install.last_seen_at.desc())
        if since is not None:
            q = q.where(Install.first_seen_at >= since)
        rows = [[(_fmt_dt(i.first_seen_at), _fmt_dt(i.first_seen_at)),
                 _fmt_dt(i.last_seen_at), i.product or "—", i.plan or "—",
                 i.app_version or "—", i.os_name or "—",
                 (str(i.heartbeat_count), i.heartbeat_count or 0),
                 (i.install_id or "")[:10]]
                for i in db.scalars(q).all()]
        t = _table(["First seen", "Last seen", "Product", "Plan", "Version", "OS", "Heartbeats", "Install id"], rows)
        return _shell("Installs", bar + f"<h2>Installs · {_html.escape(lbl)} · {len(rows)}</h2>" + back + t)

    if view == "licences":
        q = select(License).order_by(License.created_at.desc())
        if since is not None:
            q = q.where(License.created_at >= since)
        rows = [[_fmt_dt(l.created_at), l.license_key or "—", l.product or "—", l.plan or "—",
                 l.customer_email or "—", l.company_name or "",
                 str(l.expires_at) if l.expires_at else "—",
                 "revoked" if l.revoked else "active"]
                for l in db.scalars(q).all() if not is_internal(l.customer_email)]
        t = _table(["Created", "Key", "Product", "Plan", "Customer", "Company", "Expires", "Status"], rows)
        return _shell("Licences", bar + f"<h2>Licences · {_html.escape(lbl)} · {len(rows)}</h2>" + back + t)

    if view == "contacts":
        rows = _contacts(db, since)
        dl = f'<p><a class="btn" href="?days={days}&view=contacts&format=csv">⬇ Download CSV</a></p>'
        trows = [[c["email"], c["name"], c["product"], c["status"],
                  (str(c["orders"]), c["orders"]), (_rupees(c["paid"]), c["paid"]),
                  _fmt_dt(c["last"])] for c in rows]
        t = _table(["Email", "Name", "Product", "Status", "Orders", "Paid", "Last activity"], trows)
        return _shell("Contacts / audience",
                      bar + f"<h2>Contacts · {_html.escape(lbl)} · {len(rows)}</h2>" + back + dl
                      + "<p style='color:#8aa0bd;font-size:12px'>Everyone who reached checkout or holds a licence — your marketing audience.</p>" + t)

    if view == "aispend":
        q = select(AIUsageLog).order_by(AIUsageLog.created_at.desc())
        if since is not None:
            q = q.where(AIUsageLog.created_at >= since)
        rows = [[_fmt_dt(a.created_at), a.feature or "—", a.model or "—",
                 (f"{a.tokens_in or 0:,}", a.tokens_in or 0),
                 (f"{a.tokens_out or 0:,}", a.tokens_out or 0),
                 (_rupees(a.paise_charged), a.paise_charged or 0),
                 "ok" if a.success else "fail", a.error or ""]
                for a in db.scalars(q.limit(1000)).all()]
        t = _table(["Time", "Feature", "Model", "Tokens in", "Tokens out",
                    "Cost", "Status", "Error"], rows)
        return _shell("AI spend", bar + f"<h2>AI usage · {_html.escape(lbl)} · "
                      f"{len(rows)}</h2>" + back + t)

    if view == "wallet":
        # Current unspent balances (not period-filtered — these are live).
        q = select(Credit).where(Credit.balance_paise > 0).order_by(
            Credit.balance_paise.desc())
        rows = [[(str(c.license_id or "—"), c.license_id or 0),
                 (_rupees(c.balance_paise), c.balance_paise or 0),
                 _fmt_dt(c.updated_at)]
                for c in db.scalars(q).all()]
        t = _table(["Licence id", "Balance", "Updated"], rows)
        return _shell("Wallet liability",
                      bar + f"<h2>Unspent credits · {len(rows)} wallet(s)</h2>"
                      + back + "<p style='color:#8aa0bd;font-size:12px'>Live "
                      "balances we still owe in service — not period-filtered.</p>"
                      + t)

    if view == "checks":
        q = select(ValidationLog).order_by(ValidationLog.created_at.desc())
        if since is not None:
            q = q.where(ValidationLog.created_at >= since)
        rows = [[_fmt_dt(v.created_at), v.license_key or "—",
                 (v.machine_id or "")[:12], v.app_version or "—", v.ip or "",
                 "ok" if v.success else "fail", v.error or ""]
                for v in db.scalars(q.limit(500)).all()]
        t = _table(["Time", "Key", "Machine", "Version", "IP", "Status",
                    "Error"], rows)
        return _shell("Licence checks",
                      bar + f"<h2>Validations · {_html.escape(lbl)} · "
                      f"{len(rows)} (latest 500)</h2>" + back + t)

    return _shell("Dashboard", back + "<p>Unknown view.</p>")


# ── contacts (shared by view + CSV) ──────────────────────────────────────────
def _contacts(db: Session, since):
    """Aggregate one row per email from orders (+ licences), within the period
    by last activity. status = customer (has paid) | lead (only created)."""
    by_email = {}
    q = select(Order)
    if since is not None:
        q = q.where(Order.created_at >= since)
    for o in db.scalars(q).all():
        em = (o.customer_email or "").strip().lower()
        if not em or is_internal(em):
            continue
        c = by_email.setdefault(em, {"email": em, "name": "", "product": o.product or "",
                                     "status": "lead", "orders": 0, "paid": 0, "last": o.created_at})
        c["orders"] += 1
        if o.customer_name and not c["name"]:
            c["name"] = o.customer_name
        if o.status == "paid":
            c["status"] = "customer"
            c["paid"] += int(o.amount_paise or 0)
        if o.created_at and (c["last"] is None or o.created_at > c["last"]):
            c["last"] = o.created_at
    return sorted(by_email.values(), key=lambda c: (c["status"] != "customer", -(c["last"].timestamp() if c["last"] else 0)))


def contacts_csv(db: Session, days: int) -> str:
    rows = _contacts(db, _since(days))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email", "name", "product", "status", "orders", "paid_inr", "last_activity"])
    for c in rows:
        w.writerow([c["email"], c["name"], c["product"], c["status"], c["orders"],
                    f"{(c['paid'] or 0)/100:.0f}", _fmt_dt(c["last"])])
    return buf.getvalue()


# ── entry point ──────────────────────────────────────────────────────────────
def render_dashboard(db: Session, days: int = 30, view: str = "", q: str = "") -> str:
    try:
        days = int(days)
    except Exception:
        days = 30
    view = (view or "").strip().lower()
    if view in ("orders", "leads", "installs", "licences", "contacts",
                "aispend", "wallet", "checks"):
        return _view(db, view, days)
    return _overview(db, days)
