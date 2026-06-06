"""
Sandbox (Quicko GSP) client — server-side GSTR-2B pull.

The desktop app NEVER holds the GSP key; it calls this server, which proxies
to Sandbox and debits the wallet per pull. This is REPORTS/reconcile data
(read the 2B to reconcile the books), NOT compliance/filing.

Proven live flow (2026-06-06) — see project-accgenie-gst-pro-reports memory:
  1. POST /authenticate                         (x-api-key/secret) -> app token (24h)
  2. POST /gst/compliance/tax-payer/otp          (x-source:primary; body {username,gstin}) -> OTP to mobile
  3. POST /gst/compliance/tax-payer/otp/verify?otp=NNN  (body {username,gstin}) -> 6h session token
  4. GET  /gst/compliance/tax-payer/gstrs/gstr-2b/{year}/{month}  (authorization: session token)
        -> data.data.data.docdata.b2b[] = [{ctin, inv:[{inum,dt,txval,igst,cgst,sgst}]}]

Credentials come from env: SANDBOX_API_KEY / SANDBOX_API_SECRET (Fly secrets).
"""
from __future__ import annotations

import os
import time
import requests

_BASE = "https://api.sandbox.co.in"
_TIMEOUT = 60


class SandboxError(RuntimeError):
    pass


def _key_secret() -> tuple[str, str]:
    k = os.environ.get("SANDBOX_API_KEY", "").strip()
    s = os.environ.get("SANDBOX_API_SECRET", "").strip()
    if not k or not s:
        raise SandboxError("Sandbox GSP not configured (SANDBOX_API_KEY/SECRET unset).")
    return k, s


# App token cache (24h validity; refresh a little early).
_app_token: str | None = None
_app_token_exp: float = 0.0


def app_token(force: bool = False) -> str:
    global _app_token, _app_token_exp
    if not force and _app_token and time.time() < _app_token_exp:
        return _app_token
    key, secret = _key_secret()
    r = requests.post(f"{_BASE}/authenticate",
                      headers={"x-api-key": key, "x-api-secret": secret, "x-api-version": "1.0"},
                      timeout=_TIMEOUT)
    if r.status_code != 200:
        raise SandboxError(f"Sandbox auth failed ({r.status_code}): {r.text[:200]}")
    tok = (r.json().get("data") or {}).get("access_token")
    if not tok:
        raise SandboxError("Sandbox auth: no access_token in response.")
    _app_token = tok
    _app_token_exp = time.time() + 23 * 3600   # refresh ~1h early
    return tok


def _hdr(token: str) -> dict:
    key, _ = _key_secret()
    return {"authorization": token, "x-api-key": key,
            "x-source": "primary", "x-api-version": "1.0", "Content-Type": "application/json"}


def generate_otp(gstin: str, username: str) -> dict:
    """Trigger the GSTN OTP to the taxpayer's registered mobile."""
    r = requests.post(f"{_BASE}/gst/compliance/tax-payer/otp",
                      headers=_hdr(app_token()),
                      json={"username": username, "gstin": gstin}, timeout=_TIMEOUT)
    if r.status_code != 200:
        raise SandboxError(f"Generate OTP failed ({r.status_code}): {r.text[:200]}")
    return r.json().get("data") or {}


def verify_otp(gstin: str, username: str, otp: str) -> str:
    """Verify the OTP -> returns the 6-hour taxpayer session token."""
    r = requests.post(f"{_BASE}/gst/compliance/tax-payer/otp/verify",
                      params={"otp": str(otp).strip()},
                      headers=_hdr(app_token()),
                      json={"username": username, "gstin": gstin}, timeout=_TIMEOUT)
    if r.status_code != 200:
        raise SandboxError(f"Verify OTP failed ({r.status_code}): {r.text[:200]}")
    sess = (r.json().get("data") or {}).get("access_token")
    if not sess:
        raise SandboxError("Verify OTP: no session token in response.")
    return sess


def _to_num(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def parse_2b_b2b(payload: dict) -> list[dict]:
    """Map a GSTR-2B response into the reconcile engine's row shape:
    {gstin, invoice_no, invoice_date, taxable, igst, cgst, sgst}."""
    doc = ((((payload or {}).get("data") or {}).get("data") or {}).get("data") or {}).get("docdata") or {}
    rows: list[dict] = []
    for sup in (doc.get("b2b") or []):
        ctin = (sup.get("ctin") or "").strip().upper()
        for inv in (sup.get("inv") or []):
            rows.append({
                "gstin":        ctin,
                "invoice_no":   str(inv.get("inum") or "").strip(),
                "invoice_date": str(inv.get("dt") or "").strip(),
                "taxable":      _to_num(inv.get("txval")),
                "igst":         _to_num(inv.get("igst")),
                "cgst":         _to_num(inv.get("cgst")),
                "sgst":         _to_num(inv.get("sgst")),
            })
    return rows


def fetch_2b(session_token: str, gstin: str, year: str, month: str) -> list[dict]:
    """Fetch GSTR-2B for a return period -> normalised B2B invoice rows."""
    url = f"{_BASE}/gst/compliance/tax-payer/gstrs/gstr-2b/{year}/{int(month):02d}"
    r = requests.get(url, headers={"authorization": session_token,
                                   "x-api-key": _key_secret()[0], "x-api-version": "1.0.0"},
                     timeout=_TIMEOUT)
    if r.status_code != 200:
        raise SandboxError(f"GSTR-2B fetch failed ({r.status_code}): {r.text[:200]}")
    return parse_2b_b2b(r.json())
