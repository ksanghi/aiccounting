"""Admin email blast ("Announcements").

Segment licence holders (the people who got a key at checkout — free or paid)
and send them a product update. Marketing-compliant: every email carries a
one-click unsubscribe, and suppressed addresses are never mailed.

Admin-only (the routes in main.py gate on the ADMIN_TOKEN). Sending runs in a
background task so the HTTP request returns immediately; results land in the
EmailBlast log, visible on the page after a refresh.
"""
from __future__ import annotations

import hashlib
import hmac
import html as _html
import re
import time
from datetime import date
from urllib.parse import quote

# Accounts HQ logo (hosted on the marketing site) — shown in campaign emails.
LOGO_URL = "https://aic.ai-consultants.in/img/accountshq.png"

from sqlalchemy import select
from sqlalchemy.orm import Session

from license_server.config import settings
from license_server.models import License, EmailSuppression, EmailBlast, EmailSend
from license_server.services import email_service

BASE_URL = "https://accgenie-license-in.fly.dev"

PRODUCTS = ["", "accgenie", "rwagenie"]
PLANS = ["", "FREE", "STANDARD", "PRO", "PREMIUM"]
STATUSES = ["", "active", "expired"]

# How many recipient emails to actually list on the page (the full list is
# still sent — this just caps what's rendered so a huge list doesn't break it).
LIST_CAP = 500

DEFAULT_SUBJECT = "Accounts HQ just got a big update — AI is now free on every plan"

DEFAULT_BODY = """Hi,

Thanks for using Accounts HQ. We've just released version 1.1, and there's one change worth updating for right away:

AI is now included on every plan — including Free.

Drop a supplier bill or receipt and the AI reads it and posts the accounting entry for you, with GST split automatically. No more typing every voucher by hand.

Also new in this release:
- A searchable menu — press Ctrl+Q (or the menu button) and type to jump to any screen.
- A User Manual you can download anytime from Tools - User Manual.

How to update (takes a minute, and all your data is kept):
1. Download the latest version: https://apps.ai-consultants.in/downloads/AccountsHQ-Setup.exe
2. Run the downloaded file — it installs over your current version and keeps all your companies and entries.

Questions? Just reply to this email.

- The Accounts HQ team"""


# ── unsubscribe signing ────────────────────────────────────────────────────
def _sig(email: str) -> str:
    return hmac.new(settings.admin_token.encode(),
                    (email or "").strip().lower().encode(),
                    hashlib.sha256).hexdigest()[:20]


def unsubscribe_url(email: str) -> str:
    return f"{BASE_URL}/unsubscribe?e={quote(email)}&s={_sig(email)}"


def verify_unsub(email: str, s: str) -> bool:
    return hmac.compare_digest(_sig(email), (s or ""))


def suppress(db: Session, email: str) -> None:
    e = (email or "").strip().lower()
    if not e:
        return
    exists = db.scalar(select(EmailSuppression).where(EmailSuppression.email == e))
    if not exists:
        db.add(EmailSuppression(email=e))
        db.commit()


# ── recipient segmentation ─────────────────────────────────────────────────
def recipients(db: Session, product="", plan="", status="", days=0) -> list[str]:
    """Distinct, non-suppressed customer emails matching the filters."""
    supp = {e.lower() for (e,) in db.execute(select(EmailSuppression.email)).all()}
    today = date.today()
    rows = db.execute(select(
        License.customer_email, License.product, License.plan,
        License.revoked, License.expires_at, License.created_at)).all()
    out: dict[str, str] = {}
    for email, prod, pl, revoked, exp, created in rows:
        e = (email or "").strip().lower()
        if not e or "@" not in e or e in supp:
            continue
        if product and prod != product:
            continue
        if plan and (pl or "").upper() != plan:
            continue
        active = (not revoked) and (exp is None or exp >= today)
        if status == "active" and not active:
            continue
        if status == "expired" and active:
            continue
        if days and created and (today - created.date()).days > days:
            continue
        out.setdefault(e, email.strip())
    return sorted(out.values(), key=str.lower)


def filter_suppressed(db: Session, emails) -> list[str]:
    """De-dupe + drop suppressed addresses from an explicit list (the checked
    boxes). Belt-and-suspenders so a hand-picked send still honours unsubscribes."""
    supp = {e.lower() for (e,) in db.execute(select(EmailSuppression.email)).all()}
    out, seen = [], set()
    for e in emails:
        e = (e or "").strip()
        k = e.lower()
        if e and "@" in e and k not in supp and k not in seen:
            seen.add(k)
            out.append(e)
    return out


# ── compose + send ─────────────────────────────────────────────────────────
def _wrap(body_text: str, email: str, campaign: str = "") -> tuple[str, str]:
    """Build (text, html) for one recipient. `campaign` selects the context:
    "" = licence-holder announcement (default, unchanged); "ca" = the cold
    CA-firm outreach (Accounts HQ logo header + an accurate 'why you got this'
    footer instead of the 'you have a licence' line)."""
    un = unsubscribe_url(email)
    if campaign == "ca":
        reason = ("You're receiving this because you're listed publicly as a "
                  "practising chartered accountant and we thought Accounts HQ "
                  "would be useful to your firm.")
        logo_html = (f"<div style='margin:0 0 18px'><img src='{LOGO_URL}' "
                     f"alt='Accounts HQ' style='height:42px;border:0'></div>")
    else:
        reason = ("You're receiving this because you have an Accounts HQ / "
                  "RWA HQ licence.")
        logo_html = ""
    text = (body_text or "").rstrip() + f"\n\n—\n{reason}\nUnsubscribe: {un}"
    # Escape, make URLs clickable, then turn newlines into <br>.
    esc = _html.escape(body_text or "")
    esc = re.sub(r"(https?://[^\s<]+)",
                 r"<a href='\1' style='color:#0EA5A5'>\1</a>", esc)
    esc = esc.replace("\n", "<br>")
    html = (
        f"<div style='font-family:-apple-system,Segoe UI,sans-serif;font-size:14px;"
        f"color:#0F172A;line-height:1.6'>{logo_html}{esc}</div>"
        f"<hr style='margin:26px 0 10px;border:none;border-top:1px solid #e2e8f0'>"
        f"<p style='font-size:11px;color:#94a3b8;font-family:sans-serif'>{reason} "
        f"<a href='{un}' style='color:#64748b'>Unsubscribe</a>.</p>")
    return text, html


def send_blast_bg(subject: str, body_text: str, recips: list[str],
                  filters: str = "", campaign: str = "") -> None:
    """Run in a BackgroundTask. RESUMABLE + idempotent: any address already
    emailed successfully in a prior run is skipped, so if the server restarts
    mid-blast (e.g. a deploy), simply re-firing continues where it left off.
    Sends over ONE reused SMTP connection (email_service.send_bulk) rather than
    a fresh connect per email, which shared relays rate-limit. Logs the blast +
    one row per recipient, with counts committed every 25 so progress is durable.
    """
    from license_server.db import SessionLocal
    db = SessionLocal()
    try:
        # Never email the same address twice — skip prior successful sends.
        already = {e.lower() for (e,) in db.execute(
            select(EmailSend.email).where(EmailSend.ok.is_(True))).all()}
        todo = [e for e in recips if e and e.lower() not in already]

        blast = EmailBlast(subject=subject[:256], filters=filters[:256],
                           sent_count=0, failed_count=0)
        db.add(blast)
        db.commit()
        db.refresh(blast)

        def _messages():
            for email in todo:
                text, html = _wrap(body_text, email, campaign)
                yield (email, subject, text, html)

        sent = failed = 0
        for email, ok in email_service.send_bulk(_messages()):
            sent += 1 if ok else 0
            failed += 0 if ok else 1
            db.add(EmailSend(blast_id=blast.id, email=email, ok=bool(ok)))
            if (sent + failed) % 25 == 0:
                blast.sent_count = sent
                blast.failed_count = failed
                db.commit()
        blast.sent_count = sent
        blast.failed_count = failed
        db.commit()
    finally:
        db.close()


def nav_bar(token: str, active: str = "") -> str:
    """Shared top nav linking the admin reporting pages (token carried)."""
    tk = quote(token or "")

    def lnk(href, label, key):
        weight = "700" if key == active else "500"
        col = "#0f172a" if key == active else "#0ea5a5"
        return (f"<a href='{href}?token={tk}' style='margin-right:18px;"
                f"text-decoration:none;font-weight:{weight};color:{col}'>{label}</a>")

    return ("<div style='padding:0 0 12px;margin-bottom:16px;"
            "border-bottom:1px solid #e2e8f0;font-size:14px'>"
            + lnk("/admin/dashboard", "📊 Dashboard", "dash")
            + lnk("/admin/traffic", "📈 Traffic", "traffic")
            + lnk("/admin/announce", "📧 Email blast", "announce")
            + lnk("/admin/chat-review", "💬 Chat review", "chat")
            + lnk("/admin/health", "🩺 Health", "health")
            + lnk("/admin/ca-leads", "📝 CA leads", "caleads")
            + lnk("/admin/rwahq-leads", "🏙️ RWA leads", "rwaleads")
            + "</div>")


def render_blast_detail(db: Session, token: str, blast_id: int) -> str:
    """The exact recipient list for one blast — email · status · time."""
    blast = db.get(EmailBlast, blast_id)
    if blast is None:
        return nav_bar(token, "announce") + "<p>Blast not found.</p>"
    sends = db.execute(select(EmailSend).where(
        EmailSend.blast_id == blast_id).order_by(
        EmailSend.ok, EmailSend.email)).scalars().all()
    rows = "".join(
        f"<tr><td style='padding:7px 8px;border-bottom:1px solid #eef2f7'>{_html.escape(s.email)}</td>"
        f"<td style='padding:7px 8px;border-bottom:1px solid #eef2f7;font-weight:600;"
        f"color:{'#059669' if s.ok else '#b91c1c'}'>{'sent' if s.ok else 'failed'}</td>"
        f"<td style='padding:7px 8px;border-bottom:1px solid #eef2f7;color:#64748b'>"
        f"{s.created_at:%H:%M:%S}</td></tr>" for s in sends) or (
        "<tr><td colspan=3 style='color:#94a3b8;padding:8px'>No per-recipient "
        "records for this blast (it was sent before the sent-list feature).</td></tr>")
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Sent list — {_html.escape(blast.subject)}</title>
<style>body{{font-family:-apple-system,Segoe UI,sans-serif;background:#f8fafc;color:#0f172a;max-width:700px;margin:0 auto;padding:24px}}
table{{width:100%;border-collapse:collapse;font-size:13px;background:#fff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden}}
th{{text-align:left;padding:8px;background:#f1f5f9;font-size:12px;color:#475569}} a{{color:#0ea5a5}}</style></head><body>
{nav_bar(token, "announce")}
<h2 style="font-size:19px">📧 {_html.escape(blast.subject)}</h2>
<p style="color:#475569;font-size:13px">{blast.created_at:%Y-%m-%d %H:%M} · <b>{blast.sent_count}</b> sent · <b style="color:#b91c1c">{blast.failed_count}</b> failed · filters: {_html.escape(blast.filters or '—')}</p>
<table><tr><th>Email</th><th>Status</th><th>Time</th></tr>{rows}</table>
</body></html>"""


# ── admin page ─────────────────────────────────────────────────────────────
def _opts(values, sel):
    out = []
    for v in values:
        label = v or "— any —"
        s = " selected" if v == sel else ""
        out.append(f"<option value='{_html.escape(v)}'{s}>{_html.escape(label)}</option>")
    return "".join(out)


def render_announce_page(db: Session, token: str, product="", plan="",
                         status="", days=0, subject="", body="",
                         notice="") -> str:
    recips = recipients(db, product, plan, status, days)
    n = len(recips)
    subject = subject or DEFAULT_SUBJECT
    body = body or DEFAULT_BODY
    boxes = "".join(
        f"<label style='display:flex;align-items:center;gap:10px;padding:8px 8px;"
        f"border-bottom:1px solid #eef2f7;cursor:pointer'>"
        f"<input type='checkbox' name='recipient' value='{_html.escape(e)}' checked "
        f"style='margin:0;flex:0 0 auto;width:16px;height:16px'>"
        f"<span style='line-height:1.2;word-break:break-all'>{_html.escape(e)}</span>"
        f"</label>" for e in recips[:LIST_CAP])
    if not boxes:
        boxes = "<span style='color:#94a3b8'>No emails match these filters.</span>"
    overflow = (f"<div style='color:#b45309;font-size:11px;margin-top:6px'>Showing the first "
                f"{LIST_CAP}; {n - LIST_CAP} more match but aren't individually selectable here."
                f"</div>" if n > LIST_CAP else "")
    recip_list_html = (
        f"<details style='margin:0 0 14px' open>"
        f"<summary style='cursor:pointer;color:#0ea5a5;font-size:13px;font-weight:600'>"
        f"👁 {n} target email{'' if n == 1 else 's'} — untick anyone to skip</summary>"
        f"<div style='margin:6px 0;font-size:12px'>"
        f"<a href='#' onclick=\"document.querySelectorAll('input[name=recipient]').forEach(c=>c.checked=true);return false\">select all</a> · "
        f"<a href='#' onclick=\"document.querySelectorAll('input[name=recipient]').forEach(c=>c.checked=false);return false\">select none</a></div>"
        f"<div style='max-height:280px;overflow:auto;background:#fff;border:1px solid #e2e8f0;"
        f"border-radius:8px;padding:10px;font-size:12px;font-family:monospace'>{boxes}</div>"
        f"{overflow}</details>")
    recent = db.execute(select(EmailBlast).order_by(
        EmailBlast.created_at.desc()).limit(8)).scalars().all()
    log_rows = "".join(
        f"<tr><td>{b.created_at:%Y-%m-%d %H:%M}</td>"
        f"<td><a href='/admin/announce/blast/{b.id}?token={quote(token)}'>{_html.escape(b.subject)}</a></td>"
        f"<td>{_html.escape(b.filters)}</td><td style='text-align:right'>{b.sent_count}</td>"
        f"<td style='text-align:right;color:#b91c1c'>{b.failed_count}</td></tr>"
        for b in recent) or "<tr><td colspan=5 style='color:#94a3b8'>No blasts sent yet.</td></tr>"
    notice_html = (f"<div style='background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;"
                   f"padding:10px 14px;border-radius:8px;margin-bottom:16px'>{_html.escape(notice)}</div>"
                   if notice else "")
    tk = _html.escape(token)
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Email blast — Announcements</title>
<style>
body{{font-family:-apple-system,Segoe UI,sans-serif;background:#f8fafc;color:#0f172a;max-width:780px;margin:0 auto;padding:24px}}
h1{{font-size:22px}} label{{display:block;font-size:12px;font-weight:600;color:#475569;margin:10px 0 4px}}
input,select,textarea{{width:100%;padding:9px 11px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;font-family:inherit}}
.row{{display:flex;gap:12px}} .row>div{{flex:1}}
.count{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px;margin:14px 0;font-size:15px}}
.count b{{font-size:22px;color:#0ea5a5}}
button{{padding:11px 18px;border-radius:8px;font-weight:700;font-size:14px;border:none;cursor:pointer}}
.preview{{background:#fff;border:1px solid #cbd5e1;color:#334155;margin-right:8px}}
.send{{background:#0ea5a5;color:#fff}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}}
td,th{{padding:7px 8px;border-bottom:1px solid #e2e8f0;text-align:left}}
a{{color:#0ea5a5}}
</style></head><body>
{nav_bar(token, "announce")}
<h1>📧 Email blast — Announcements</h1>
<p style="color:#475569;font-size:13px">Send a product update to licence holders. Every email includes a one-click unsubscribe; suppressed addresses are skipped automatically.</p>
{notice_html}
<form method="post" action="/admin/announce/send">
  <input type="hidden" name="token" value="{tk}">
  <div class="row">
    <div><label>Product</label><select name="product">{_opts(PRODUCTS, product)}</select></div>
    <div><label>Plan</label><select name="plan">{_opts(PLANS, plan)}</select></div>
    <div><label>Status</label><select name="status">{_opts(STATUSES, status)}</select></div>
    <div><label>Acquired in last (days, 0=all)</label><input name="days" value="{days}"></div>
  </div>
  <div class="count">This will go to <b>{n}</b> recipient{'' if n==1 else 's'}.
    <a href="/admin/announce?token={tk}&product={quote(product)}&plan={quote(plan)}&status={quote(status)}&days={days}">↻ refresh count</a></div>
  {recip_list_html}
  <label>Subject</label><input name="subject" value="{_html.escape(subject)}" required>
  <label>Message</label><textarea name="body" rows="10" required>{_html.escape(body)}</textarea>
  <label>Send a test only to (optional — leave blank to send the real blast)</label>
  <input name="test_email" placeholder="you@example.com">
  <div style="margin-top:16px">
    <button class="send" type="submit">Send →</button>
  </div>
</form>
<h3 style="margin-top:28px">Recent blasts</h3>
<table><tr><th>When</th><th>Subject</th><th>Filters</th><th style="text-align:right">Sent</th><th style="text-align:right">Failed</th></tr>{log_rows}</table>
</body></html>"""
