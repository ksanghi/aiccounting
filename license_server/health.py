"""Admin health checks — a 12-hourly self-test of the live system, with an
ops-email alert on any failure.

Built after a Razorpay webhook silently stopped verifying for ~24h and the
only signal was Razorpay's own disable email. These checks surface that class
of silent breakage (dead webhook, download 404, runaway bounce rate) within
12 hours instead of days.
"""
from __future__ import annotations

import hashlib
import hmac
import html as _html
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import quote

from sqlalchemy import func, select

from license_server.config import settings
from license_server.models import License
from license_server.services import email_service

BASE_URL = "https://accgenie-license-in.fly.dev"
INSTALLER_URL = "https://apps.ai-consultants.in/downloads/AccountsHQ-Setup.exe"
BOUNCE_ALERT_RATE = 0.05          # alert if the 7-day hard-bounce rate > 5%


def _http_status(url: str, timeout: int = 15) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def _brevo(path: str, key: str, timeout: int = 20):
    req = urllib.request.Request(
        "https://api.brevo.com/v3" + path,
        headers={"api-key": key, "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def run_checks(db) -> list[dict]:
    """Return [{name, ok, detail}] for each subsystem."""
    out: list[dict] = []

    # 1. Database
    try:
        n = db.scalar(select(func.count()).select_from(License))
        out.append({"name": "Database", "ok": True, "detail": f"{n} licences"})
    except Exception as e:
        out.append({"name": "Database", "ok": False, "detail": str(e)[:140]})

    # 2. Razorpay webhook — a self-signed ping proves the route + secret +
    #    verification path all work end to end (a real webhook signed with a
    #    mismatched secret would 401, which is what disabled it).
    secret = (settings.razorpay_webhook_secret or "").encode()
    if not secret:
        out.append({"name": "Razorpay webhook", "ok": False,
                    "detail": "RAZORPAY_WEBHOOK_SECRET not set"})
    else:
        body = b'{"event":"healthcheck"}'
        sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
        try:
            req = urllib.request.Request(
                BASE_URL + "/webhooks/razorpay", data=body, method="POST",
                headers={"content-type": "application/json",
                         "x-razorpay-signature": sig})
            with urllib.request.urlopen(req, timeout=15) as r:
                st = r.status
            out.append({"name": "Razorpay webhook", "ok": st == 200,
                        "detail": f"self-ping HTTP {st}"})
        except urllib.error.HTTPError as e:
            out.append({"name": "Razorpay webhook", "ok": False,
                        "detail": f"self-ping HTTP {e.code}"})
        except Exception as e:
            out.append({"name": "Razorpay webhook", "ok": False,
                        "detail": str(e)[:140]})
    out.append({
        "name": "Razorpay keys",
        "ok": bool(settings.razorpay_key_id and settings.razorpay_key_secret),
        "detail": "configured" if settings.razorpay_key_id else "missing"})

    # 3. Installer download (the free-download target)
    st = _http_status(INSTALLER_URL)
    out.append({"name": "Installer download", "ok": st == 200,
                "detail": f"HTTP {st}"})

    # 4. Brevo — API reachable + 7-day hard-bounce rate under threshold
    key = (settings.brevo_api_key or "").strip()
    if not key:
        out.append({"name": "Brevo email", "ok": False, "detail": "no API key"})
    else:
        try:
            rep = _brevo("/smtp/statistics/aggregatedReport?days=7", key)
            req_n = rep.get("requests") or 0
            hb = rep.get("hardBounces") or 0
            rate = (hb / req_n) if req_n else 0.0
            out.append({"name": "Brevo bounce rate (7d)",
                        "ok": rate <= BOUNCE_ALERT_RATE,
                        "detail": f"{hb}/{req_n} = {rate * 100:.1f}% "
                                  f"(limit {BOUNCE_ALERT_RATE * 100:.0f}%)"})
        except Exception as e:
            out.append({"name": "Brevo email", "ok": False,
                        "detail": str(e)[:140]})

    # 5. Recent activity — informational
    try:
        cutoff = datetime.utcnow() - timedelta(days=7)
        n = db.scalar(select(func.count()).select_from(License).where(
            License.created_at >= cutoff))
        out.append({"name": "New licences (7d)", "ok": True, "detail": str(n)})
    except Exception as e:
        out.append({"name": "New licences (7d)", "ok": False,
                    "detail": str(e)[:140]})

    return out


def run_and_alert(db) -> list[dict]:
    """Run the checks; email the ops address if anything failed."""
    checks = run_checks(db)
    failed = [c for c in checks if not c["ok"]]
    if failed and (settings.ops_alert_email or "").strip():
        report = "\n".join(
            f"  [{'OK  ' if c['ok'] else 'FAIL'}] {c['name']}: {c['detail']}"
            for c in checks)
        body = (f"AIC health check found {len(failed)} problem(s).\n\n"
                f"{report}\n\nDashboard: {BASE_URL}/admin/health\n")
        for addr in [a.strip() for a in settings.ops_alert_email.split(",")
                     if a.strip()]:
            email_service.send_email(
                to_email=addr,
                subject=(f"[ALERT] AIC health: {len(failed)} issue(s) — "
                         + ", ".join(c["name"] for c in failed)),
                body_text=body)
    return checks


def render_health_page(token: str, checks: list[dict]) -> str:
    from license_server.announce import nav_bar
    n_fail = sum(1 for c in checks if not c["ok"])
    col = "#b91c1c" if n_fail else "#059669"
    banner = "All systems normal." if not n_fail else f"{n_fail} check(s) FAILING."
    rows = "".join(
        f"<tr><td style='padding:9px 10px;border-bottom:1px solid #eef2f7'>"
        f"{_html.escape(c['name'])}</td>"
        f"<td style='padding:9px 10px;border-bottom:1px solid #eef2f7;"
        f"font-weight:700;color:{'#059669' if c['ok'] else '#b91c1c'}'>"
        f"{'OK' if c['ok'] else 'FAIL'}</td>"
        f"<td style='padding:9px 10px;border-bottom:1px solid #eef2f7;"
        f"color:#475569'>{_html.escape(str(c['detail']))}</td></tr>"
        for c in checks)
    tk = quote(token or "")
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Health</title>
<style>body{{font-family:-apple-system,Segoe UI,sans-serif;background:#f8fafc;color:#0f172a;max-width:760px;margin:0 auto;padding:24px}}
table{{width:100%;border-collapse:collapse;font-size:14px;background:#fff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden}}
th{{text-align:left;padding:9px 10px;background:#f1f5f9;font-size:12px;color:#475569}} a{{color:#0ea5a5}}</style></head><body>
{nav_bar(token, "health")}
<h1 style="font-size:22px">🩺 System health</h1>
<div style="background:#fff;border:1px solid #e2e8f0;border-left:4px solid {col};border-radius:8px;padding:12px 16px;margin:10px 0;font-weight:600;color:{col}">{banner}</div>
<p style="color:#475569;font-size:13px">Auto-runs every 12 hours and emails {_html.escape(settings.ops_alert_email or '—')} on any failure. <a href="/admin/health/run?token={tk}">↻ run now</a></p>
<table><tr><th>Check</th><th>Status</th><th>Detail</th></tr>{rows}</table>
</body></html>"""
