"""
DocInbox — the hub of the AI Document Inbox.

ONE watched folder per company is the hub. Email (their own mailbox,
read-only), the ADF scanner, and manual drops are just *feeders* into it;
this one module + the inbox_documents table is the review-and-process
queue the accountant works through. We never build email-ingest and
scan-ingest twice — every feeder just drops a file into the incoming
folder, and ingest() picks it up the same way.

Pipeline:  ingest -> classify -> route -> review/approve -> post.

This module owns ingest + the queue's status transitions. The AI steps
live in ai/doc_classifier.py (classify) and ai/voucher_ai.py (extract).
The UI is ui/document_inbox_page.py.

No third-party deps — stdlib only. The DocumentParser/VoucherAI/AI calls
are invoked by the UI layer (they may be slow / need threading), not here.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from core.paths import inbox_dir

# File types we accept into the inbox (superset of DocumentParser.SUPPORTED;
# the parser rejects anything it can't read with a clear message).
SUPPORTED_EXT = {
    ".pdf", ".jpg", ".jpeg", ".png", ".xlsx", ".xls", ".csv", ".txt", ".docx",
}

# doc_types that route to a concrete handler; everything else holds as 'other'.
ROUTABLE_TYPES = (
    "purchase_invoice", "sales_invoice", "debit_note", "credit_note",
    "bank_statement",
)

SOURCE_EMAIL  = "EMAIL"
SOURCE_SCAN   = "SCAN"
SOURCE_MANUAL = "MANUAL"

# Status values (mirror the inbox_documents.status comment in core/models.py).
ST_PENDING    = "PENDING"
ST_CLASSIFIED = "CLASSIFIED"
ST_APPROVED   = "APPROVED"
ST_POSTED     = "POSTED"
ST_REJECTED   = "REJECTED"
ST_ERROR      = "ERROR"

_SAFE = "-_.() "


def _slugify_company(name: str) -> str:
    """Mirror the company-slug rule used for the .db filename so a company's
    inbox folder is stable across sessions."""
    keep = [c if (c.isalnum() or c in "-_") else "_" for c in (name or "company")]
    s = "".join(keep).strip("_").lower()
    return s or "company"


def _clean_fragment(s: str, limit: int = 40) -> str:
    """Make an arbitrary string safe + tidy for a filename fragment."""
    s = (s or "").strip()
    out = "".join(c if (c.isalnum() or c in _SAFE) else " " for c in s)
    out = " ".join(out.split())            # collapse whitespace
    return out[:limit].strip()


def nice_name(orig_name: str, source: str, arrived: datetime,
              email_meta: dict | None = None) -> str:
    """
    Build a readable local name from what we know AT ARRIVAL (before AI).

      EMAIL : 2026-06-06 Reliance Energy invoice.pdf   (date · sender · subject/file)
      SCAN  : 2026-06-06 scan 14-32-05.pdf
      MANUAL: keeps the original name

    The review queue may auto-rename to vendor+number AFTER extraction.
    """
    ext = Path(orig_name).suffix.lower() or ".pdf"
    stamp = arrived.strftime("%Y-%m-%d")
    meta = email_meta or {}
    if source == SOURCE_EMAIL:
        who = _clean_fragment(meta.get("from_name") or meta.get("from") or "email", 30)
        what = _clean_fragment(meta.get("subject") or Path(orig_name).stem, 40)
        base = " ".join(p for p in (stamp, who, what) if p) or stamp
    elif source == SOURCE_SCAN:
        base = f"{stamp} scan {arrived.strftime('%H-%M-%S')}"
    else:
        base = _clean_fragment(Path(orig_name).stem, 80) or f"{stamp} document"
    return f"{base}{ext}"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _unique_path(store: Path, name: str) -> Path:
    """Avoid clobbering if two arrivals produce the same nice name."""
    cand = store / name
    if not cand.exists():
        return cand
    stem, ext = Path(name).stem, Path(name).suffix
    i = 2
    while (store / f"{stem} ({i}){ext}").exists():
        i += 1
    return store / f"{stem} ({i}){ext}"


class DocInbox:
    """Per-company document inbox. Construct with the live sqlite connection,
    the company_id, and the company name (for the stable folder slug)."""

    def __init__(self, conn: sqlite3.Connection, company_id: int,
                 company_name: str):
        self.conn = conn
        self.company_id = company_id
        self.slug = _slugify_company(company_name)
        self.root = inbox_dir(self.slug)

    # ── folders ──────────────────────────────────────────────────────────
    @property
    def incoming_dir(self) -> Path:
        return self.root / "incoming"

    @property
    def store_dir(self) -> Path:
        return self.root / "store"

    # ── ingest ───────────────────────────────────────────────────────────
    def ingest_file(self, src_path: str | Path, source: str = SOURCE_MANUAL,
                    email_meta: dict | None = None,
                    move: bool = False) -> dict | None:
        """
        Bring one file into the inbox: hash + dedup, copy into the managed
        store under a nice name, insert a PENDING row.

        Returns the new row as a dict, or None if it was a duplicate or an
        unsupported type. `move=True` removes the source (used for the
        watched incoming folder); `move=False` copies (used for a manual
        pick the user may want to keep where it is).
        """
        src = Path(src_path)
        if not src.is_file() or src.suffix.lower() not in SUPPORTED_EXT:
            return None

        file_hash = _hash_file(src)
        dup = self.conn.execute(
            "SELECT id FROM inbox_documents WHERE company_id=? AND file_hash=?",
            (self.company_id, file_hash),
        ).fetchone()
        if dup:
            if move:
                try:
                    src.unlink()       # already have it; clear the drop zone
                except OSError:
                    pass
            return None

        arrived = datetime.now()
        stored_name = nice_name(src.name, source, arrived, email_meta)
        dest = _unique_path(self.store_dir, stored_name)
        if move:
            shutil.move(str(src), str(dest))
        else:
            shutil.copy2(str(src), str(dest))

        cur = self.conn.execute(
            """INSERT INTO inbox_documents
                   (company_id, source, orig_name, stored_name, stored_path,
                    file_hash, email_meta, arrived_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (self.company_id, source, src.name, dest.name, str(dest),
             file_hash, json.dumps(email_meta) if email_meta else None,
             arrived.strftime("%Y-%m-%d %H:%M:%S"), ST_PENDING),
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def scan_incoming(self) -> int:
        """Pick up every supported file sitting in the incoming drop zone
        (fed by the scanner / a manual drop) and ingest it. Returns the
        count newly ingested. Files are MOVED out of incoming on success."""
        n = 0
        for f in sorted(self.incoming_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXT:
                if self.ingest_file(f, source=SOURCE_SCAN, move=True):
                    n += 1
        return n

    # ── queue reads ──────────────────────────────────────────────────────
    def get(self, doc_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM inbox_documents WHERE id=? AND company_id=?",
            (doc_id, self.company_id),
        ).fetchone()
        return dict(row) if row else None

    def list(self, statuses: tuple[str, ...] | None = None) -> list[dict]:
        sql = "SELECT * FROM inbox_documents WHERE company_id=?"
        args: list = [self.company_id]
        if statuses:
            sql += " AND status IN (%s)" % ",".join("?" * len(statuses))
            args += list(statuses)
        sql += " ORDER BY arrived_at DESC, id DESC"
        return [dict(r) for r in self.conn.execute(sql, args)]

    def pending_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM inbox_documents "
            "WHERE company_id=? AND status IN (?, ?)",
            (self.company_id, ST_PENDING, ST_CLASSIFIED),
        ).fetchone()
        return int(row[0]) if row else 0

    # ── status transitions ───────────────────────────────────────────────
    def set_classified(self, doc_id: int, doc_type: str, confidence: float,
                        ai_meta: dict) -> None:
        self.conn.execute(
            """UPDATE inbox_documents
                  SET status=?, doc_type=?, ai_confidence=?, ai_meta=?, error=NULL
                WHERE id=? AND company_id=?""",
            (ST_CLASSIFIED, doc_type, float(confidence),
             json.dumps(ai_meta), doc_id, self.company_id),
        )
        self.conn.commit()

    def set_doc_type(self, doc_id: int, doc_type: str) -> None:
        """Accountant override of the AI's type guess before approving."""
        self.conn.execute(
            "UPDATE inbox_documents SET doc_type=? WHERE id=? AND company_id=?",
            (doc_type, doc_id, self.company_id),
        )
        self.conn.commit()

    def mark_posted(self, doc_id: int, voucher_id: int | None = None,
                    bank_statement_id: int | None = None,
                    user_id: int | None = None) -> None:
        self.conn.execute(
            """UPDATE inbox_documents
                  SET status=?, voucher_id=?, bank_statement_id=?,
                      reviewed_by_user_id=?, reviewed_at=datetime('now'),
                      error=NULL
                WHERE id=? AND company_id=?""",
            (ST_POSTED, voucher_id, bank_statement_id, user_id,
             doc_id, self.company_id),
        )
        self.conn.commit()

    def mark_rejected(self, doc_id: int, user_id: int | None = None,
                      notes: str = "") -> None:
        self.conn.execute(
            """UPDATE inbox_documents
                  SET status=?, reviewed_by_user_id=?,
                      reviewed_at=datetime('now'), notes=?
                WHERE id=? AND company_id=?""",
            (ST_REJECTED, user_id, notes or None, doc_id, self.company_id),
        )
        self.conn.commit()

    def mark_error(self, doc_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE inbox_documents SET status=?, error=? "
            "WHERE id=? AND company_id=?",
            (ST_ERROR, str(error)[:1000], doc_id, self.company_id),
        )
        self.conn.commit()

    def rename_stored(self, doc_id: int, new_stem: str) -> None:
        """Optional post-extraction rename to vendor+number. Renames the file
        on disk and updates the row; silently no-ops on a filesystem error."""
        doc = self.get(doc_id)
        if not doc:
            return
        old = Path(doc["stored_path"])
        if not old.exists():
            return
        clean = _clean_fragment(new_stem, 80)
        if not clean:
            return
        new_path = _unique_path(self.store_dir, f"{clean}{old.suffix.lower()}")
        try:
            old.rename(new_path)
        except OSError:
            return
        self.conn.execute(
            "UPDATE inbox_documents SET stored_name=?, stored_path=? "
            "WHERE id=? AND company_id=?",
            (new_path.name, str(new_path), doc_id, self.company_id),
        )
        self.conn.commit()
