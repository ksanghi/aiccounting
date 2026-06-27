"""
Bill-wise referencing — Tally "bill-by-bill" / "Against Reference".

AccGenie is balance-based; this module adds optional OPEN-ITEM tracking on top:
every SALES / PURCHASE invoice creates a *bill reference* (an outstanding), and
RECEIPT / PAYMENT vouchers allocate against specific open bills. The result is
bill-by-bill outstanding + aging-by-bill, alongside the existing party-FIFO view.

Design notes
------------
- **Never breaks posting.** VoucherEngine.post() calls `on_voucher_posted()`
  inside its own try/except *after* the voucher is committed, so a bug here can
  at worst skip a bill record — it can't roll back a real voucher.
- **Recording is cheap + always on.** One `bill_references` row per
  sales/purchase invoice (negligible), so the feature works retroactively when a
  user enables it. The *UI + reports* are what's gated by the `bill_wise_refs`
  licence flag (PRO/PREMIUM) — see ui/feature gating.
- v1 allocation kinds: **AGAINST** (settle a specific open bill) and
  **ON_ACCOUNT** (unallocated). NEW-reference / ADVANCE are recorded as
  on-account for now (TODO: model advances as their own open item).

Tables: `bill_references` (the open bills) + `bill_allocations` (settlements).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


# Voucher types that CREATE a bill (party owes / we owe).
_BILL_TYPES = {"SALES", "PURCHASE"}
# Voucher types that SETTLE bills.
_SETTLE_TYPES = {"RECEIPT", "PAYMENT"}
# Notes adjust an existing outstanding.
_NOTE_TYPES = {"CREDIT_NOTE", "DEBIT_NOTE"}

_DEBTORS = "Sundry Debtors"
_CREDITORS = "Sundry Creditors"


@dataclass
class Allocation:
    """One allocation line attached to a receipt/payment draft."""
    bill_ref_id: int | None          # None for on-account
    amount: float
    alloc_type: str = "AGAINST"      # AGAINST | ON_ACCOUNT | NEW | ADVANCE


class BillWiseEngine:
    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    # ── group helpers ────────────────────────────────────────────────────
    def _ledger_group(self, ledger_id: int) -> str:
        row = self.db.execute(
            """SELECT g.name FROM ledgers l
               JOIN account_groups g ON l.group_id = g.id
               WHERE l.id = ? AND l.company_id = ?""",
            (ledger_id, self.company_id),
        ).fetchone()
        return row["name"] if row else ""

    def _party_line(self, lines, group_name: str):
        """Return the (ledger_id, net) of the first line whose ledger is in
        `group_name`. net = dr - cr (debtor) flipped by caller as needed."""
        for ln in lines:
            if self._ledger_group(ln.ledger_id) == group_name:
                return ln.ledger_id, (ln.dr_amount - ln.cr_amount)
        return None, 0.0

    # ── write path (called from post) ────────────────────────────────────
    def record_bill(self, ledger_id: int, bill_number: str, bill_date: str,
                    amount: float, voucher_id: int,
                    ref_type: str = "BILL") -> int:
        cur = self.db.execute(
            """INSERT INTO bill_references
               (company_id, ledger_id, bill_number, bill_date, bill_amount,
                pending_amount, voucher_id, ref_type)
               VALUES (?,?,?,?,?,?,?,?)""",
            (self.company_id, ledger_id, bill_number, bill_date,
             round(amount, 2), round(amount, 2), voucher_id, ref_type),
        )
        return cur.lastrowid

    def allocate(self, voucher_id: int, ledger_id: int,
                 allocations: list) -> None:
        """Apply receipt/payment allocations. AGAINST decrements a specific
        open bill; everything else is recorded on-account."""
        for a in allocations:
            bill_ref_id = getattr(a, "bill_ref_id", None) if not isinstance(a, dict) else a.get("bill_ref_id")
            amount = float(getattr(a, "amount", 0) if not isinstance(a, dict) else a.get("amount", 0))
            alloc_type = (getattr(a, "alloc_type", "AGAINST") if not isinstance(a, dict) else a.get("alloc_type", "AGAINST")) or "AGAINST"
            if amount <= 0:
                continue
            if alloc_type == "AGAINST" and bill_ref_id:
                self.db.execute(
                    """UPDATE bill_references
                       SET pending_amount = ROUND(pending_amount - ?, 2)
                       WHERE id = ? AND company_id = ?""",
                    (round(amount, 2), bill_ref_id, self.company_id),
                )
            else:
                bill_ref_id = None
            self.db.execute(
                """INSERT INTO bill_allocations
                   (company_id, bill_ref_id, voucher_id, ledger_id, amount,
                    alloc_type)
                   VALUES (?,?,?,?,?,?)""",
                (self.company_id, bill_ref_id, voucher_id, ledger_id,
                 round(amount, 2), alloc_type),
            )

    def reverse_for_voucher(self, voucher_id: int) -> None:
        """Undo this voucher's bill-wise effects (on cancel / before re-edit).
        Restores pending on bills this voucher settled, deletes those
        allocations, and removes bills this voucher *created* if nothing else
        has settled against them."""
        # 1. restore pending for AGAINST allocations made by this voucher
        for r in self.db.execute(
            """SELECT bill_ref_id, amount FROM bill_allocations
               WHERE voucher_id = ? AND company_id = ?
                 AND bill_ref_id IS NOT NULL""",
            (voucher_id, self.company_id),
        ).fetchall():
            self.db.execute(
                """UPDATE bill_references
                   SET pending_amount = ROUND(pending_amount + ?, 2)
                   WHERE id = ? AND company_id = ?""",
                (r["amount"], r["bill_ref_id"], self.company_id),
            )
        self.db.execute(
            "DELETE FROM bill_allocations WHERE voucher_id = ? AND company_id = ?",
            (voucher_id, self.company_id),
        )
        # 2. drop bills this voucher created, if untouched by other settlements
        for b in self.db.execute(
            "SELECT id FROM bill_references WHERE voucher_id = ? AND company_id = ?",
            (voucher_id, self.company_id),
        ).fetchall():
            used = self.db.execute(
                "SELECT COUNT(*) AS c FROM bill_allocations WHERE bill_ref_id = ?",
                (b["id"],),
            ).fetchone()
            if not used or not used["c"]:
                self.db.execute(
                    "DELETE FROM bill_references WHERE id = ?", (b["id"],))

    def on_voucher_posted(self, voucher_id: int, draft) -> None:
        """Dispatch by voucher type. Called from VoucherEngine.post() after the
        voucher is committed. Defensive — caller wraps in try/except."""
        vtype = draft.voucher_type
        if vtype == "SALES":
            lid, net = self._party_line(draft.lines, _DEBTORS)
            if lid and net > 0:
                self.record_bill(lid, draft.reference or "", draft.voucher_date,
                                 net, voucher_id)
        elif vtype == "PURCHASE":
            lid, net = self._party_line(draft.lines, _CREDITORS)
            if lid and net < 0:   # creditor sits on Cr side
                self.record_bill(lid, draft.reference or "", draft.voucher_date,
                                 -net, voucher_id)
        elif vtype in _SETTLE_TYPES:
            allocs = list(getattr(draft, "allocations", []) or [])
            if not allocs:
                return
            grp = _DEBTORS if vtype == "RECEIPT" else _CREDITORS
            lid, _ = self._party_line(draft.lines, grp)
            if lid:
                self.allocate(voucher_id, lid, allocs)

    # ── read path (reports + UI) ─────────────────────────────────────────
    def open_bills(self, ledger_id: int) -> list[dict]:
        """Open bills (pending != 0) for one party, oldest first."""
        rows = self.db.execute(
            """SELECT id, bill_number, bill_date, bill_amount, pending_amount,
                      ref_type, voucher_id
               FROM bill_references
               WHERE company_id = ? AND ledger_id = ?
                 AND ROUND(pending_amount, 2) <> 0
               ORDER BY bill_date, id""",
            (self.company_id, ledger_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def bill_outstanding(self, group_name: str = _DEBTORS) -> dict:
        """Every open bill across all parties in a group (Debtors/Creditors)."""
        rows = self.db.execute(
            """SELECT l.name AS party, b.bill_number, b.bill_date,
                      b.bill_amount, b.pending_amount, b.ref_type
               FROM bill_references b
               JOIN ledgers l ON b.ledger_id = l.id
               JOIN account_groups g ON l.group_id = g.id
               WHERE b.company_id = ? AND g.name = ?
                 AND ROUND(b.pending_amount, 2) <> 0
               ORDER BY l.name, b.bill_date, b.id""",
            (self.company_id, group_name),
        ).fetchall()
        items = [dict(r) for r in rows]
        total = round(sum(i["pending_amount"] for i in items), 2)
        return {"group": group_name, "rows": items, "total": total}

    def aging_by_bill(self, as_of: str, group_name: str = _DEBTORS) -> dict:
        """Bucket each open bill by age = as_of - bill_date."""
        as_of_d = date.fromisoformat(as_of)
        out = self.bill_outstanding(group_name)
        buckets = {"b0_30": 0.0, "b31_60": 0.0, "b61_90": 0.0, "b90p": 0.0}
        rows = []
        for r in out["rows"]:
            try:
                age = (as_of_d - date.fromisoformat(r["bill_date"])).days
            except Exception:
                age = 0
            if age <= 30:
                bk = "b0_30"
            elif age <= 60:
                bk = "b31_60"
            elif age <= 90:
                bk = "b61_90"
            else:
                bk = "b90p"
            buckets[bk] += r["pending_amount"]
            rows.append({**r, "age_days": age, "bucket": bk})
        buckets = {k: round(v, 2) for k, v in buckets.items()}
        return {"as_of": as_of, "group": group_name, "rows": rows,
                "buckets": buckets, "total": out["total"]}
