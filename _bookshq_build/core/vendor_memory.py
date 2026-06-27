"""Vendor cache for document-AI (A4).

When the accountant accepts an AI-drafted voucher for a vendor/party, we
remember the ledger mapping they accepted (voucher type + Dr/Cr ledgers). The
next document from the SAME vendor is pre-filled with that mapping, so repeat
invoices stop needing correction.

Keyed by the normalised vendor name the AI extracts ("party"). Per company.
Storage table `ai_vendor_memory` is created by core.models' SCHEMA.
"""
from __future__ import annotations

# ── PARKED (off for initial release) ───────────────────────────────────────
# The vendor cache is built and tested, but auto-filling repeat invoices is
# advanced behaviour that's risky to ship before users trust basic document
# ingestion. So it's OFF by default: remember()/recall() no-op, the hooks in
# the document reader call them but nothing is learned or applied. The table,
# the module, and the AI's "party" field all stay live, so turning it on later
# is a ONE-LINE change — flip this to True in a release once ingestion is
# proven in the field.
VENDOR_CACHE_ENABLED = False


def _key(vendor: str) -> str:
    """Normalise a vendor name for matching — lowercase, collapse whitespace."""
    return " ".join((vendor or "").strip().lower().split())


def remember(db, company_id: int, vendor: str, *,
             voucher_type: str, dr_ledger: str, cr_ledger: str,
             gst_rate: float = 0.0) -> None:
    """Record (or reinforce) the mapping the user accepted for this vendor."""
    if not VENDOR_CACHE_ENABLED:
        return
    k = _key(vendor)
    if not k or not (dr_ledger and cr_ledger):
        return
    db.execute(
        """
        INSERT INTO ai_vendor_memory
            (company_id, vendor_key, voucher_type, dr_ledger, cr_ledger,
             gst_rate, hits, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, datetime('now'))
        ON CONFLICT(company_id, vendor_key) DO UPDATE SET
            voucher_type = excluded.voucher_type,
            dr_ledger    = excluded.dr_ledger,
            cr_ledger    = excluded.cr_ledger,
            gst_rate     = excluded.gst_rate,
            hits         = ai_vendor_memory.hits + 1,
            updated_at   = datetime('now')
        """,
        (company_id, k, voucher_type or "", dr_ledger, cr_ledger, float(gst_rate or 0)),
    )
    db.commit()


def recall(db, company_id: int, vendor: str) -> dict | None:
    """Return the remembered mapping for a vendor, or None."""
    if not VENDOR_CACHE_ENABLED:
        return None
    k = _key(vendor)
    if not k:
        return None
    r = db.execute(
        "SELECT voucher_type, dr_ledger, cr_ledger, gst_rate, hits "
        "FROM ai_vendor_memory WHERE company_id=? AND vendor_key=?",
        (company_id, k),
    ).fetchone()
    return dict(r) if r else None
