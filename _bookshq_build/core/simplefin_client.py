"""
SimpleFIN client — free-to-us US bank feed (the customer pays the SimpleFIN
Bridge ~$15/yr; we register nothing and hold no key).

Protocol (https://www.simplefin.org/protocol.html):
  1. The customer creates a one-time **setup token** at the SimpleFIN Bridge.
  2. claim_setup_token(token)  -> decodes it (base64 claim URL), POSTs to claim,
     returns a long-lived **access URL** that embeds basic-auth credentials:
       https://<user>:<pass>@bridge.simplefin.org/simplefin
     Store that per linked connection; the token is single-use.
  3. fetch_accounts(access_url, start_date, end_date) -> JSON with accounts +
     transactions.
  4. account_to_parse_result(account) -> the SAME ParseResult the file parsers
     produce, so BankReconciler imports a SimpleFIN account exactly like an OFX
     file (date / signed amount / narration / reference), with NO engine changes.

Stdlib only (urllib) — no third-party HTTP dependency.
"""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from core.local_statement_parser import ParseResult, _parse_amount


class SimpleFinError(Exception):
    pass


# SimpleFIN Bridge sits behind Cloudflare, which 403s the default
# "Python-urllib/x" agent. Send a browser-ish UA that also identifies the app.
_UA = "Mozilla/5.0 (compatible; AccGenie-BooksHQ/1.0; +https://apps.ai-consultants.in)"


# ── date helpers ─────────────────────────────────────────────────────────────
def _epoch_to_iso(posted) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(posted), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _iso_to_epoch(iso_date: str) -> int:
    return int(datetime.strptime(iso_date, "%Y-%m-%d")
               .replace(tzinfo=timezone.utc).timestamp())


# ── protocol ─────────────────────────────────────────────────────────────────
def claim_setup_token(setup_token: str) -> str:
    """Exchange a one-time setup token for the long-lived access URL."""
    token = (setup_token or "").strip()
    if not token:
        raise SimpleFinError("Empty setup token.")
    try:
        claim_url = base64.b64decode(token).decode("utf-8").strip()
    except Exception as e:
        raise SimpleFinError("Setup token is not valid base64.") from e
    if not claim_url.lower().startswith("http"):
        raise SimpleFinError("Setup token did not decode to a claim URL.")
    req = urllib.request.Request(claim_url, data=b"", method="POST")
    req.add_header("User-Agent", _UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            access_url = resp.read().decode("utf-8").strip()
    except Exception as e:
        raise SimpleFinError(f"Could not claim the setup token: {e}") from e
    if not access_url.lower().startswith("http"):
        raise SimpleFinError("Claim did not return a valid access URL.")
    return access_url


def _split_access_url(access_url: str):
    """'https://user:pass@host/path' -> (base_url_without_creds, user, pass)."""
    p = urllib.parse.urlparse(access_url)
    user = urllib.parse.unquote(p.username or "")
    pw = urllib.parse.unquote(p.password or "")
    netloc = p.hostname or ""
    if p.port:
        netloc += f":{p.port}"
    base = urllib.parse.urlunparse((p.scheme, netloc, p.path, "", "", ""))
    return base, user, pw


def fetch_accounts(access_url: str, start_date: Optional[str] = None,
                   end_date: Optional[str] = None, pending: bool = False) -> dict:
    """GET {access_url}/accounts -> parsed JSON. Dates are ISO yyyy-mm-dd."""
    base, user, pw = _split_access_url(access_url)
    url = base.rstrip("/") + "/accounts"
    params = {}
    if start_date:
        params["start-date"] = _iso_to_epoch(start_date)
    if end_date:
        params["end-date"] = _iso_to_epoch(end_date)
    if pending:
        params["pending"] = "1"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _UA)
    if user or pw:
        cred = base64.b64encode(f"{user}:{pw}".encode()).decode()
        req.add_header("Authorization", "Basic " + cred)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise SimpleFinError(f"Could not fetch accounts: {e}") from e


# ── mapping into the engine's shape ──────────────────────────────────────────
def list_accounts(data: dict) -> list[dict]:
    """Light summary for the UI: which accounts the customer linked."""
    out = []
    for a in data.get("accounts", []) or []:
        org = a.get("org") or {}
        out.append({
            "id":       a.get("id"),
            "name":     a.get("name") or "",
            "org":      org.get("name") or org.get("domain") or "",
            "currency": a.get("currency") or "",
            "balance":  a.get("balance"),
            "txn_count": len(a.get("transactions", []) or []),
        })
    return out


def account_to_parse_result(account: dict) -> ParseResult:
    """One SimpleFIN account -> the same ParseResult the file parsers emit.
    SimpleFIN amount is a signed string (negative = money out = DR)."""
    org = account.get("org") or {}
    lines: list[dict] = []
    for i, t in enumerate(account.get("transactions", []) or []):
        amt = _parse_amount(t.get("amount"))
        txn_date = _epoch_to_iso(t.get("posted") or t.get("transacted_at"))
        if amt is None or amt == 0 or not txn_date:
            continue
        narration = (t.get("description") or t.get("payee") or t.get("memo") or "").strip()
        lines.append({
            "line_index": i,
            "txn_date":   txn_date,
            "amount":     round(abs(amt), 2),
            "sign":       "DR" if amt < 0 else "CR",
            "narration":  narration,
            "reference":  str(t.get("id") or ""),
            "raw_row":    [json.dumps(t)[:300]],
        })
    if not lines:
        return ParseResult(success=False, bank_name=org.get("name"),
                           account_number=str(account.get("id") or ""),
                           error="No transactions in this SimpleFIN account for the period.")
    return ParseResult(
        success=True,
        bank_name=org.get("name"),
        account_number=str(account.get("id") or ""),
        statement_closing=_parse_amount(account.get("balance")),
        lines=lines,
    )
