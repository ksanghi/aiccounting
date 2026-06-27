"""
EmailFetcher — the email *feeder* for the Document Inbox.

The customer points us at a folder/label in THEIR OWN mailbox. We connect
read-only over IMAP (a feeder, not a host — nothing routes through our
servers), pull NEW message attachments incrementally by UID, and drop them
into the inbox's incoming/ staging folder. The Document Inbox then ingests
them exactly like a scan or a manual drop ("same folder, same processing").

Design choices:
- READ-ONLY: we `select(folder, readonly=True)` and track the last UID we
  processed, so we NEVER mark messages read, move, or delete. The mailbox
  is untouched.
- UNIVERSAL: plain IMAP + an app-password works with Gmail, Outlook/M365,
  Yahoo, Zoho, and any provider — no per-provider OAuth app registration.
  (OAuth XOAUTH2 can slot into `_login()` later for a one-click connect.)
- LOCAL ONLY: config + the app-password live in the per-user config dir,
  the password lightly obfuscated and machine-bound. Stdlib only.

This module does NOT touch the DB — it just lands files + returns metadata.
The UI layer ingests them via DocInbox.ingest_file(source=EMAIL, meta=...).
"""
from __future__ import annotations

import base64
import email
import hashlib
import imaplib
import json
import re
import ssl
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr
from pathlib import Path

from core.paths import config_dir

_CFG_PATH = config_dir() / "email_inbox.json"

# Supported attachment types (mirror DocInbox.SUPPORTED_EXT).
_SUPPORTED_EXT = {
    ".pdf", ".jpg", ".jpeg", ".png", ".xlsx", ".xls", ".csv", ".txt", ".docx",
}

# Common providers → (imap_host, port). Anything else: user enters the host.
KNOWN_IMAP = {
    "gmail.com":      ("imap.gmail.com", 993),
    "googlemail.com": ("imap.gmail.com", 993),
    "outlook.com":    ("outlook.office365.com", 993),
    "hotmail.com":    ("outlook.office365.com", 993),
    "live.com":       ("outlook.office365.com", 993),
    "office365.com":  ("outlook.office365.com", 993),
    "yahoo.com":      ("imap.mail.yahoo.com", 993),
    "yahoo.in":       ("imap.mail.yahoo.com", 993),
    "zoho.com":       ("imap.zoho.com", 993),
    "zohomail.in":    ("imap.zoho.in", 993),
    "icloud.com":     ("imap.mail.me.com", 993),
    "rediffmail.com": ("imap.rediffmail.com", 993),
}

_FIRST_RUN_DAYS = 14   # first fetch only looks back this far, then incremental


def guess_host(emailaddr: str) -> tuple[str, int]:
    """Best-effort IMAP host/port from the email domain ('' if unknown)."""
    domain = (emailaddr.split("@", 1)[-1] if "@" in emailaddr else "").lower().strip()
    if domain in KNOWN_IMAP:
        return KNOWN_IMAP[domain]
    if domain:
        return (f"imap.{domain}", 993)   # a sane guess the user can correct
    return ("", 993)


# ── light, machine-bound obfuscation for the stored app-password ──────────────
# Not a vault — the desktop already stores the Anthropic key locally. This just
# keeps the password from sitting in plain sight in a JSON file, and ties it to
# this machine so a copied config file is useless elsewhere.

def _machine_key() -> bytes:
    try:
        from core.license_manager import LicenseManager
        seed = LicenseManager.get_machine_id()
    except Exception:
        import platform
        seed = platform.node() + platform.machine()
    return hashlib.sha256(("accgenie-email::" + seed).encode()).digest()


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def obfuscate(plaintext: str) -> str:
    if not plaintext:
        return ""
    return base64.b64encode(_xor(plaintext.encode("utf-8"), _machine_key())).decode()


def deobfuscate(blob: str) -> str:
    if not blob:
        return ""
    try:
        return _xor(base64.b64decode(blob.encode()), _machine_key()).decode("utf-8")
    except Exception:
        return ""


@dataclass
class EmailConfig:
    enabled:   bool = False
    email:     str  = ""
    host:      str  = ""
    port:      int  = 993
    password:  str  = ""          # obfuscated on disk; plaintext in memory
    folder:    str  = "INBOX"     # the label/folder to watch
    last_uid:  int  = 0           # highest UID processed (incremental, read-only)
    created:   str  = ""          # ISO date the config was first saved

    def redacted(self) -> dict:
        d = asdict(self)
        d["password"] = "********" if self.password else ""
        return d


# ── persistence (per-company, keyed by slug) ──────────────────────────────────

def _read_all() -> dict:
    try:
        if _CFG_PATH.exists():
            with open(_CFG_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def load_config(slug: str) -> EmailConfig:
    raw = _read_all().get(slug)
    if not raw:
        return EmailConfig()
    cfg = EmailConfig(**{k: v for k, v in raw.items() if k in EmailConfig.__dataclass_fields__})
    cfg.password = deobfuscate(raw.get("password", ""))
    return cfg


def save_config(slug: str, cfg: EmailConfig) -> None:
    allcfg = _read_all()
    stored = asdict(cfg)
    stored["password"] = obfuscate(cfg.password)
    if not cfg.created:
        cfg.created = datetime.now().strftime("%Y-%m-%d")
        stored["created"] = cfg.created
    allcfg[slug] = stored
    _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CFG_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(allcfg, f, indent=2)
    tmp.replace(_CFG_PATH)


# ── header / filename helpers ─────────────────────────────────────────────────

def _decode(s) -> str:
    if not s:
        return ""
    out = []
    for txt, enc in decode_header(s):
        if isinstance(txt, bytes):
            try:
                out.append(txt.decode(enc or "utf-8", errors="replace"))
            except Exception:
                out.append(txt.decode("utf-8", errors="replace"))
        else:
            out.append(txt)
    return "".join(out).strip()


def _safe_filename(name: str, fallback_ext: str = ".pdf") -> str:
    name = _decode(name) or f"attachment{fallback_ext}"
    name = name.replace("\r", " ").replace("\n", " ")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().strip(".")
    return name or f"attachment{fallback_ext}"


# ── connection ────────────────────────────────────────────────────────────────

class EmailFetchError(Exception):
    pass


def _connect(cfg: EmailConfig) -> imaplib.IMAP4_SSL:
    if not cfg.host:
        raise EmailFetchError("No IMAP host set.")
    try:
        ctx = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(cfg.host, cfg.port or 993, ssl_context=ctx)
    except Exception as e:
        raise EmailFetchError(f"Could not reach {cfg.host}:{cfg.port}: {e}")
    try:
        conn.login(cfg.email, cfg.password)
    except imaplib.IMAP4.error as e:
        # Gmail/Yahoo/etc. reject the normal password — they need an
        # app-specific password. Surface that clearly.
        raise EmailFetchError(
            f"Login failed: {e}. If this is Gmail/Yahoo/Outlook, use an "
            f"app-password (not your normal password) and enable IMAP."
        )
    return conn


def test_connection(cfg: EmailConfig) -> tuple[bool, str]:
    """Return (ok, message). Logs in, selects the folder read-only, logs out."""
    try:
        conn = _connect(cfg)
    except EmailFetchError as e:
        return False, str(e)
    try:
        typ, _ = conn.select(cfg.folder, readonly=True)
        if typ != "OK":
            # Offer the folder list to help them pick the right label.
            names = _list_folders(conn)
            hint = ("  Available: " + ", ".join(names[:12])) if names else ""
            return False, f"Folder '{cfg.folder}' not found.{hint}"
        return True, f"Connected. Folder '{cfg.folder}' is reachable."
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _list_folders(conn: imaplib.IMAP4_SSL) -> list[str]:
    out = []
    try:
        typ, data = conn.list()
        if typ == "OK":
            for raw in data:
                line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
                m = re.search(r'"([^"]+)"\s*$', line) or re.search(r'([^ ]+)\s*$', line)
                if m:
                    out.append(m.group(1))
    except Exception:
        pass
    return out


def list_folders(cfg: EmailConfig) -> list[str]:
    """Folder/label names in the mailbox (for the setup picker)."""
    try:
        conn = _connect(cfg)
    except EmailFetchError:
        return []
    try:
        return _list_folders(conn)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# ── fetch ─────────────────────────────────────────────────────────────────────

def fetch_new(cfg: EmailConfig, dest_dir: str | Path) -> tuple[int, list[dict]]:
    """
    Download NEW attachments (incrementally, read-only) into dest_dir.

    Mutates cfg.last_uid to the highest UID seen. The CALLER is responsible
    for save_config() afterwards so the cursor advances. Returns:

        (new_uid_count_scanned, [
            {"path": <abs staged file>, "from": <email>, "from_name": <name>,
             "subject": <subj>, "date": <iso>},
            ...
        ])

    Each saved attachment is a dict the UI ingests with source=EMAIL +
    email_meta so the Document Inbox names it date·sender·subject.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    conn = _connect(cfg)
    saved: list[dict] = []
    scanned = 0
    try:
        typ, _ = conn.select(cfg.folder, readonly=True)
        if typ != "OK":
            raise EmailFetchError(f"Folder '{cfg.folder}' not found.")

        if cfg.last_uid and cfg.last_uid > 0:
            crit = f"UID {cfg.last_uid + 1}:*"
            typ, data = conn.uid("search", None, crit)
        else:
            since = (datetime.now() - timedelta(days=_FIRST_RUN_DAYS)).strftime("%d-%b-%Y")
            typ, data = conn.uid("search", None, "SINCE", since)
        if typ != "OK" or not data or not data[0]:
            return 0, []

        uids = [int(x) for x in data[0].split()]
        # UID n:* can return the last message even when nothing is newer.
        uids = [u for u in uids if u > cfg.last_uid]
        max_uid = cfg.last_uid

        for uid in uids:
            scanned += 1
            typ, msg_data = conn.uid("fetch", str(uid), "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                max_uid = max(max_uid, uid)
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            from_name, from_addr = parseaddr(_decode(msg.get("From")))
            subject = _decode(msg.get("Subject"))
            try:
                date_iso = email.utils.parsedate_to_datetime(
                    msg.get("Date")).strftime("%Y-%m-%d")
            except Exception:
                date_iso = datetime.now().strftime("%Y-%m-%d")

            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                disp = (part.get("Content-Disposition") or "").lower()
                fname = part.get_filename()
                if not fname and "attachment" not in disp:
                    continue
                fname = _safe_filename(fname or f"attachment_{uid}")
                if Path(fname).suffix.lower() not in _SUPPORTED_EXT:
                    continue
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                # Stage under a UID-prefixed unique name; DocInbox renames it
                # to the nice date·sender·subject form on ingest.
                staged = dest / f"u{uid}_{fname}"
                i = 2
                while staged.exists():
                    staged = dest / f"u{uid}_{Path(fname).stem} ({i}){Path(fname).suffix}"
                    i += 1
                with open(staged, "wb") as f:
                    f.write(payload)
                saved.append({
                    "path": str(staged),
                    "from": from_addr or "",
                    "from_name": from_name or from_addr or "",
                    "subject": subject,
                    "date": date_iso,
                })
            max_uid = max(max_uid, uid)

        cfg.last_uid = max_uid
        return scanned, saved
    finally:
        try:
            conn.logout()
        except Exception:
            pass
