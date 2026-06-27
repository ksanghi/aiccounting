"""
Free DIRECT GSTR-2B pull from the GST portal (A17) — desktop-side, no GSP.

Unlike the paid Sandbox/Quicko route (license_server/sandbox_gst.py), this logs in
to services.gst.gov.in with the TAXPAYER'S OWN credentials + captcha + OTP, fetches
GSTR-2B, and feeds the SAME source-agnostic reconcile engine
(reports_engine.gstr2b_reconcile). Read-only, user-driven, free.

The GST portal's data APIs use the GSTN encryption envelope (the same scheme the GSP
APIs use, documented in the GST API spec):

  • client makes a random 32-byte AES key ("app key");
  • it is RSA-encrypted with the GSTN public key and sent on login;
  • the server returns an `sek` (session/state key) AES-ECB-encrypted with the app key;
  • all data responses (`rek`/`data`) are base64 + AES-ECB-encrypted with the sek.

Endpoint paths, the exact login field set, and the GSTN public key are CALIBRATED on the
first live pull with the user's login (reverse-engineered portals always need one lock-in
pass — exactly how the Sandbox flow was proven on 2026-06-06 with the user relaying the
OTP). They are isolated as constants/at the top of each method so calibration is a
one-line change, not a rewrite.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Optional

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.asymmetric import padding as _apad
from cryptography.hazmat.primitives import serialization

_BASE = "https://services.gst.gov.in"
_TIMEOUT = 60

# Calibration constants (locked on the first live pull):
_CAPTCHA_PATH  = "/services/captcha"
_AUTH_PATH     = "/services/api/authenticate"
_OTP_PATH      = "/services/api/auth/otprequest"        # if the portal asks for OTP
_2B_PATH_TPL   = "/services/api/returns/gstr2b/get2b"   # query: rtnprd=MMYYYY
# The GSTN public key (PEM) the app-key is RSA-wrapped with — pinned at calibration.
_GSTN_PUBKEY_PEM: bytes = b""


class GstPortalError(RuntimeError):
    pass


# ── AES-256-ECB envelope (cryptography lib; GSTN uses ECB on PKCS7-padded data) ──
def _aes_ecb_decrypt(key: bytes, b64_ciphertext: str) -> bytes:
    raw = base64.b64decode(b64_ciphertext)
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    out = dec.update(raw) + dec.finalize()
    pad = out[-1]
    return out[:-pad] if 1 <= pad <= 16 else out


def _aes_ecb_encrypt(key: bytes, data: bytes) -> str:
    pad = 16 - (len(data) % 16)
    data = data + bytes([pad]) * pad
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return base64.b64encode(enc.update(data) + enc.finalize()).decode()


def _rsa_wrap(app_key: bytes) -> str:
    if not _GSTN_PUBKEY_PEM:
        raise GstPortalError("GSTN public key not pinned yet (calibrate on first live pull).")
    pub = serialization.load_pem_public_key(_GSTN_PUBKEY_PEM)
    enc = pub.encrypt(app_key, _apad.PKCS1v15())
    return base64.b64encode(enc).decode()


class GstPortalDirect:
    """One taxpayer session against the live GST portal. Construct, get_captcha(),
    login(), then fetch_2b()."""

    def __init__(self, username: str, gstin: str = ""):
        self.username = username.strip()
        self.gstin = gstin.strip().upper()
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{_BASE}/services/login",
        })
        self.app_key = os.urandom(32)   # AES-256 app key for this session
        self.sek: Optional[bytes] = None

    # 1) captcha image bytes → the UI shows it, the user types the text
    def get_captcha(self) -> bytes:
        r = self.s.get(f"{_BASE}{_CAPTCHA_PATH}", timeout=_TIMEOUT)
        if r.status_code != 200 or not r.content:
            raise GstPortalError(f"Captcha fetch failed ({r.status_code}).")
        return r.content

    # 2) login with username + password + captcha → establish the session key (sek)
    def login(self, password: str, captcha: str) -> dict:
        body = {
            "username": self.username,
            "password": password,
            "captcha": captcha.strip(),
            "rek": _rsa_wrap(self.app_key),   # app key, RSA-wrapped for the server
        }
        r = self.s.post(f"{_BASE}{_AUTH_PATH}", json=body, timeout=_TIMEOUT)
        if r.status_code != 200:
            raise GstPortalError(self._err("Login", r))
        data = r.json() if r.content else {}
        sek_enc = data.get("sek") or data.get("rek")
        if sek_enc:
            self.sek = _aes_ecb_decrypt(self.app_key, sek_enc)
        return data   # may carry {"otp_required": true} → caller calls verify_otp

    # 2b) some logins then require the registered-mobile OTP
    def verify_otp(self, otp: str) -> dict:
        r = self.s.post(f"{_BASE}{_OTP_PATH}",
                        json={"username": self.username, "otp": str(otp).strip()},
                        timeout=_TIMEOUT)
        if r.status_code != 200:
            raise GstPortalError(self._err("OTP verify", r))
        return r.json() if r.content else {}

    # 3) fetch + decrypt GSTR-2B for a return period (MMYYYY, e.g. "042026")
    def fetch_2b(self, ret_period: str) -> dict:
        if not self.sek:
            raise GstPortalError("Not logged in (no session key).")
        r = self.s.get(f"{_BASE}{_2B_PATH_TPL}",
                       params={"rtnprd": ret_period, "gstin": self.gstin},
                       timeout=_TIMEOUT)
        if r.status_code != 200:
            raise GstPortalError(self._err("GSTR-2B fetch", r))
        body = r.json() if r.content else {}
        enc = body.get("data") or body.get("rek")
        if enc:                                  # encrypted envelope → decrypt with sek
            return json.loads(_aes_ecb_decrypt(self.sek, enc).decode("utf-8"))
        return body                              # already-plain (calibration variant)

    @staticmethod
    def _err(stage: str, r: requests.Response) -> str:
        return f"{stage} failed ({r.status_code}): {r.text[:200]}"


def to_reconcile_rows(payload: dict) -> list[dict]:
    """Map the portal's GSTR-2B payload to the reconcile engine's row shape — the SAME
    shape the GSP path's parse_2b_b2b produces, so gstr2b_reconcile is unchanged."""
    doc = ((((payload or {}).get("data") or {}).get("docdata")
            or (payload or {}).get("docdata")) or {})
    rows: list[dict] = []
    for sup in (doc.get("b2b") or []):
        ctin = (sup.get("ctin") or "").strip().upper()
        for inv in (sup.get("inv") or []):
            def _n(v):
                try: return round(float(v or 0), 2)
                except (TypeError, ValueError): return 0.0
            rows.append({
                "gstin":        ctin,
                "invoice_no":   str(inv.get("inum") or "").strip(),
                "invoice_date": str(inv.get("dt") or "").strip(),
                "taxable":      _n(inv.get("txval")),
                "igst":         _n(inv.get("igst")),
                "cgst":         _n(inv.get("cgst")),
                "sgst":         _n(inv.get("sgst")),
            })
    return rows
