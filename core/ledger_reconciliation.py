"""
Ledger Reconciliation Engine

Workflow mirrors bank reco but for *party* ledgers (Sundry Debtors / Creditors,
loans, expenses, etc — anything non-bank, non-cash):

    1. import_statement      — load the party's statement file. The file
                                may state amounts from THEIR POV ("you owe me
                                Rs 100" → DR in their ledger of you) or as a
                                copy of YOUR ledger of them. The user picks
                                the sign mode at import time.
    2. auto_match            — 1-to-1 (date, amount, mirrored sign) matching
                                against your voucher_lines for that ledger.
    3. user resolves the rest — manual_match / create_voucher_for_line /
                                mark_book_line_cleared / mark_ignored / flag
    4. finalise              — snapshot into ledger_reconciliations.

Sign-mode semantics:

    sign_mode='MIRROR'   (the file is the party's ledger of YOUR account)
        Statement DR  →  matches book line cr_amount > 0  (your "I owe them")
        Statement CR  →  matches book line dr_amount > 0  (their "I owe you")

    sign_mode='SAME'     (the file IS your ledger from another system)
        Statement DR  →  matches book line dr_amount > 0
        Statement CR  →  matches book line cr_amount > 0
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from core.models import Database
from core.account_tree import AccountTree
from core.voucher_engine import VoucherEngine, VoucherDraft, PostedVoucher
from core.local_statement_parser import LocalDocumentParser


# ── Public exception types — UI listens for these ────────────────────────────

class LedgerImportError(Exception):
    """Base for ledger-statement import failures."""


class LocalParseFailed(LedgerImportError):
    def __init__(self, message: str, file_text: str = ""):
        super().__init__(message)
        self.file_text = file_text


@dataclass
class AutoMatchResult:
    matched: int
    unmatched_stmt: int
    unmatched_book: int


# ── Engine ────────────────────────────────────────────────────────────────────

class LedgerReconciler:
    """
    Constructed once per page session: LedgerReconciler(db, company_id, tree).
    Stateless — every call re-queries the DB.
    """

    def __init__(self, db: Database, company_id: int, tree: AccountTree):
        self.db = db
        self.company_id = company_id
        self.tree = tree

    # ── Imports ───────────────────────────────────────────────────────────────

    def import_statement(
        self,
        *,
        ledger_id: int,
        file_path: str,
        sign_mode: str = "MIRROR",                 # 'MIRROR' | 'SAME'
        period_from: str | None = None,
        period_to: str | None = None,
        user_id: int | None = None,
    ) -> int:
        """
        Local-only parser path. AI fallback for ledger reco isn't built yet —
        UI raises LocalParseFailed if local can't extract.
        """
        if sign_mode not in ("MIRROR", "SAME"):
            raise ValueError(f"Invalid sign_mode: {sign_mode}")
        path = Path(file_path)
        if not path.exists():
            raise ValueError(f"File not found: {file_path}")

        file_hash = self._sha256(path)
        existing = self.db.execute(
            "SELECT id FROM ledger_statements "
            "WHERE company_id=? AND ledger_id=? AND file_hash=?",
            (self.company_id, ledger_id, file_hash),
        ).fetchone()
        if existing:
            return self._reapply_period(
                existing["id"], period_from, period_to, sign_mode, user_id,
            )

        result = LocalDocumentParser().parse_bank_statement(file_path)
        if not result.success:
            raise LocalParseFailed(
                result.error or "Local parser could not read the file.",
                file_text=result.file_text,
            )

        lines = self._lines_from_parsed(result.lines)
        stmt_period_from, stmt_period_to = self._resolve_period(
            lines, period_from, period_to,
            result.period_from, result.period_to,
        )

        return self._persist_statement(
            ledger_id=ledger_id,
            file_name=path.name,
            file_hash=file_hash,
            period_from=stmt_period_from,
            period_to=stmt_period_to,
            statement_opening=result.statement_opening,
            statement_closing=result.statement_closing,
            sign_mode=sign_mode,
            import_method="LOCAL",
            imported_by_user_id=user_id,
            raw_meta=json.dumps({
                "bank_name":      result.bank_name,
                "account_number": result.account_number,
                "ext":            path.suffix.lower(),
            }),
            lines=lines,
        )

    # ── Auto-match (sign-mirror aware) ────────────────────────────────────────

    def auto_match(
        self,
        statement_id: int,
        user_id: int | None = None,
    ) -> AutoMatchResult:
        stmt = self.db.execute(
            "SELECT ledger_id, period_from, period_to, sign_mode "
            "FROM ledger_statements WHERE id=?",
            (statement_id,),
        ).fetchone()
        if not stmt:
            raise ValueError(f"Statement {statement_id} not found.")

        ledger_id   = stmt["ledger_id"]
        period_from = stmt["period_from"]
        period_to   = stmt["period_to"]
        sign_mode   = stmt["sign_mode"] or "MIRROR"

        stmt_lines = self.db.execute(
            "SELECT id, txn_date, amount, sign FROM ledger_statement_lines "
            "WHERE statement_id=? AND match_status='UNMATCHED' "
            "ORDER BY line_index",
            (statement_id,),
        ).fetchall()

        book_rows = self.db.execute(
            """SELECT vl.id AS id, v.voucher_date AS voucher_date,
                      vl.dr_amount AS dr_amount, vl.cr_amount AS cr_amount
                 FROM voucher_lines vl
                 JOIN vouchers v ON v.id = vl.voucher_id
                WHERE vl.ledger_id = ?
                  AND v.is_cancelled = 0
                  AND v.company_id = ?
                  AND v.voucher_date BETWEEN ? AND ?
                  AND (vl.party_cleared_date IS NULL OR vl.party_cleared_date = '')""",
            (ledger_id, self.company_id, period_from, period_to),
        ).fetchall()

        # Build book-side index keyed by what stmt sign would match against.
        # MIRROR: stmt DR ↔ book cr_amount, stmt CR ↔ book dr_amount.
        # SAME:   stmt DR ↔ book dr_amount, stmt CR ↔ book cr_amount.
        index: dict[tuple, list[int]] = {}
        for r in book_rows:
            for stmt_sign, book_amount in self._book_keys(r, sign_mode):
                if book_amount and book_amount > 0:
                    key = (r["voucher_date"], round(book_amount, 2), stmt_sign)
                    index.setdefault(key, []).append(r["id"])

        matched = 0
        with self.db:
            for sl in stmt_lines:
                key = (sl["txn_date"], round(sl["amount"], 2), sl["sign"])
                bucket = index.get(key)
                if not bucket:
                    continue
                vl_id = bucket.pop(0)
                self.db.execute(
                    "UPDATE ledger_statement_lines "
                    "   SET match_status='AUTO_MATCHED', "
                    "       matched_voucher_line_id=?, "
                    "       resolved_at=datetime('now'), "
                    "       resolved_by_user_id=? "
                    " WHERE id=?",
                    (vl_id, user_id, sl["id"]),
                )
                self.db.execute(
                    "UPDATE voucher_lines "
                    "   SET party_cleared_date=?, "
                    "       ledger_statement_line_id=?, "
                    "       party_cleared_by_user_id=? "
                    " WHERE id=?",
                    (sl["txn_date"], sl["id"], user_id, vl_id),
                )
                matched += 1

        unmatched_stmt = self.db.execute(
            "SELECT COUNT(*) AS c FROM ledger_statement_lines "
            "WHERE statement_id=? AND match_status='UNMATCHED'",
            (statement_id,),
        ).fetchone()["c"]

        unmatched_book = self.db.execute(
            """SELECT COUNT(*) AS c
                 FROM voucher_lines vl
                 JOIN vouchers v ON v.id = vl.voucher_id
                WHERE vl.ledger_id = ?
                  AND v.is_cancelled = 0
                  AND v.company_id = ?
                  AND v.voucher_date BETWEEN ? AND ?
                  AND (vl.party_cleared_date IS NULL OR vl.party_cleared_date = '')""",
            (ledger_id, self.company_id, period_from, period_to),
        ).fetchone()["c"]

        return AutoMatchResult(matched, unmatched_stmt, unmatched_book)

    @staticmethod
    def _book_keys(row, sign_mode: str):
        """
        Yield (stmt_sign, book_amount) pairs for a book row, given the
        sign-mode. Used to build the matching index.
        """
        if sign_mode == "MIRROR":
            yield ("DR", row["cr_amount"])    # stmt DR ↔ book Cr
            yield ("CR", row["dr_amount"])    # stmt CR ↔ book Dr
        else:                                  # SAME
            yield ("DR", row["dr_amount"])
            yield ("CR", row["cr_amount"])

    # ── Read-side queries for the UI tabs ─────────────────────────────────────

    def matched_lines(self, statement_id: int) -> list[dict]:
        rows = self.db.execute(
            """SELECT lsl.id, lsl.txn_date, lsl.amount, lsl.sign,
                      lsl.narration, lsl.reference, lsl.match_status,
                      lsl.matched_voucher_line_id,
                      v.voucher_number, v.voucher_type
                 FROM ledger_statement_lines lsl
            LEFT JOIN voucher_lines vl ON vl.id = lsl.matched_voucher_line_id
            LEFT JOIN vouchers v       ON v.id  = vl.voucher_id
                WHERE lsl.statement_id=?
                  AND lsl.match_status IN ('AUTO_MATCHED','MANUAL_MATCHED','VOUCHER_CREATED')
             ORDER BY lsl.txn_date, lsl.line_index""",
            (statement_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def unmatched_statement_lines(self, statement_id: int) -> list[dict]:
        """Lines that still need attention. IGNORED is filtered out — see
        ignored_statement_lines for those."""
        rows = self.db.execute(
            "SELECT id, txn_date, amount, sign, narration, reference, "
            "       match_status, notes "
            "  FROM ledger_statement_lines "
            " WHERE statement_id=? "
            "   AND match_status IN ('UNMATCHED','FLAGGED') "
            " ORDER BY txn_date, line_index",
            (statement_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def ignored_statement_lines(self, statement_id: int) -> list[dict]:
        """Lines the user dismissed as not needing a match (with optional note)."""
        rows = self.db.execute(
            "SELECT id, txn_date, amount, sign, narration, reference, "
            "       notes "
            "  FROM ledger_statement_lines "
            " WHERE statement_id=? AND match_status='IGNORED' "
            " ORDER BY txn_date, line_index",
            (statement_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def restore_ignored(
        self, statement_line_id: int, user_id: int | None = None,
    ) -> None:
        """Move an ignored line back to UNMATCHED so it appears in the action list again."""
        with self.db:
            self.db.execute(
                "UPDATE ledger_statement_lines "
                "   SET match_status='UNMATCHED', "
                "       resolved_at=NULL, "
                "       resolved_by_user_id=NULL, "
                "       notes=NULL "
                " WHERE id=? AND match_status='IGNORED'",
                (statement_line_id,),
            )

    def unmatched_book_lines(
        self, ledger_id: int, period_from: str, period_to: str,
    ) -> list[dict]:
        rows = self.db.execute(
            """SELECT vl.id, v.voucher_date, v.voucher_number, v.voucher_type,
                      v.narration, v.reference,
                      vl.dr_amount, vl.cr_amount
                 FROM voucher_lines vl
                 JOIN vouchers v ON v.id = vl.voucher_id
                WHERE vl.ledger_id = ?
                  AND v.is_cancelled = 0
                  AND v.company_id = ?
                  AND v.voucher_date BETWEEN ? AND ?
                  AND (vl.party_cleared_date IS NULL OR vl.party_cleared_date = '')
             ORDER BY v.voucher_date""",
            (ledger_id, self.company_id, period_from, period_to),
        ).fetchall()
        return [dict(r) for r in rows]

    def candidate_book_lines(
        self,
        ledger_id: int,
        around_date: str,
        amount: float,
        sign: str,
        sign_mode: str = "MIRROR",
        days: int = 7,
        amount_tolerance: float = 1.0,
    ) -> list[dict]:
        """For 'Find Candidate' on an unmatched stmt line."""
        from datetime import date as _date, timedelta
        try:
            d = _date.fromisoformat(around_date)
        except ValueError:
            return []
        lo = (d - timedelta(days=days)).isoformat()
        hi = (d + timedelta(days=days)).isoformat()
        amt_lo = max(0.0, amount - amount_tolerance)
        amt_hi = amount + amount_tolerance

        # Decide which book column the user-friendly candidate matches against.
        if sign_mode == "MIRROR":
            book_col = "vl.cr_amount" if sign == "DR" else "vl.dr_amount"
        else:
            book_col = "vl.dr_amount" if sign == "DR" else "vl.cr_amount"

        rows = self.db.execute(
            f"""SELECT vl.id, v.voucher_date, v.voucher_number, v.voucher_type,
                       v.narration, vl.dr_amount, vl.cr_amount
                  FROM voucher_lines vl
                  JOIN vouchers v ON v.id = vl.voucher_id
                 WHERE vl.ledger_id = ?
                   AND v.is_cancelled = 0
                   AND v.company_id = ?
                   AND v.voucher_date BETWEEN ? AND ?
                   AND (vl.party_cleared_date IS NULL OR vl.party_cleared_date = '')
                   AND {book_col} BETWEEN ? AND ?
              ORDER BY v.voucher_date""",
            (ledger_id, self.company_id, lo, hi, amt_lo, amt_hi),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Manual resolution actions ─────────────────────────────────────────────

    def manual_match(
        self, statement_line_id: int, voucher_line_id: int,
        user_id: int | None = None,
    ) -> None:
        with self.db:
            sl = self.db.execute(
                "SELECT txn_date FROM ledger_statement_lines WHERE id=?",
                (statement_line_id,),
            ).fetchone()
            if not sl:
                raise ValueError("Statement line not found.")
            self.db.execute(
                "UPDATE ledger_statement_lines "
                "   SET match_status='MANUAL_MATCHED', "
                "       matched_voucher_line_id=?, "
                "       resolved_at=datetime('now'), "
                "       resolved_by_user_id=? "
                " WHERE id=?",
                (voucher_line_id, user_id, statement_line_id),
            )
            self.db.execute(
                "UPDATE voucher_lines "
                "   SET party_cleared_date=?, "
                "       ledger_statement_line_id=?, "
                "       party_cleared_by_user_id=? "
                " WHERE id=?",
                (sl["txn_date"], statement_line_id, user_id, voucher_line_id),
            )

    def unmatch(
        self, statement_line_id: int, user_id: int | None = None,
    ) -> None:
        with self.db:
            row = self.db.execute(
                "SELECT matched_voucher_line_id "
                "  FROM ledger_statement_lines WHERE id=?",
                (statement_line_id,),
            ).fetchone()
            if not row:
                return
            vl_id = row["matched_voucher_line_id"]
            self.db.execute(
                "UPDATE ledger_statement_lines "
                "   SET match_status='UNMATCHED', "
                "       matched_voucher_line_id=NULL, "
                "       resolved_at=NULL, "
                "       resolved_by_user_id=NULL "
                " WHERE id=?",
                (statement_line_id,),
            )
            if vl_id:
                self.db.execute(
                    "UPDATE voucher_lines "
                    "   SET party_cleared_date=NULL, "
                    "       ledger_statement_line_id=NULL, "
                    "       party_cleared_by_user_id=NULL "
                    " WHERE id=?",
                    (vl_id,),
                )

    def create_voucher_for_line(
        self,
        statement_line_id: int,
        ledger_id: int,
        draft: VoucherDraft,
        user_id: int | None = None,
    ) -> PostedVoucher:
        engine = VoucherEngine(self.db, self.company_id, user_id=user_id)
        posted = engine.post(draft)
        vl_row = self.db.execute(
            "SELECT id FROM voucher_lines "
            " WHERE voucher_id=? AND ledger_id=? "
            " ORDER BY id LIMIT 1",
            (posted.voucher_id, ledger_id),
        ).fetchone()
        if not vl_row:
            raise ValueError(
                "Posted voucher has no line for the picked ledger — cannot link."
            )
        vl_id = vl_row["id"]
        sl = self.db.execute(
            "SELECT txn_date FROM ledger_statement_lines WHERE id=?",
            (statement_line_id,),
        ).fetchone()
        clear_date = sl["txn_date"] if sl else draft.voucher_date
        with self.db:
            self.db.execute(
                "UPDATE ledger_statement_lines "
                "   SET match_status='VOUCHER_CREATED', "
                "       matched_voucher_line_id=?, "
                "       resolved_at=datetime('now'), "
                "       resolved_by_user_id=? "
                " WHERE id=?",
                (vl_id, user_id, statement_line_id),
            )
            self.db.execute(
                "UPDATE voucher_lines "
                "   SET party_cleared_date=?, "
                "       ledger_statement_line_id=?, "
                "       party_cleared_by_user_id=? "
                " WHERE id=?",
                (clear_date, statement_line_id, user_id, vl_id),
            )
        return posted

    def link_voucher_to_stmt_line(
        self,
        statement_line_id: int,
        voucher_id: int,
        ledger_id: int,
        user_id: int | None = None,
    ) -> None:
        """
        After the user posts a voucher (via the Post Voucher form) for an
        unmatched stmt line, link them up: find the voucher_line on this
        voucher that uses ledger_id and mark it party-cleared against the
        statement line.
        """
        vl_row = self.db.execute(
            "SELECT id FROM voucher_lines "
            " WHERE voucher_id=? AND ledger_id=? "
            " ORDER BY id LIMIT 1",
            (voucher_id, ledger_id),
        ).fetchone()
        if not vl_row:
            raise ValueError(
                f"Posted voucher {voucher_id} has no line for ledger "
                f"{ledger_id} — cannot link."
            )
        vl_id = vl_row["id"]
        sl = self.db.execute(
            "SELECT txn_date FROM ledger_statement_lines WHERE id=?",
            (statement_line_id,),
        ).fetchone()
        if not sl:
            raise ValueError(f"Statement line {statement_line_id} not found.")
        with self.db:
            self.db.execute(
                "UPDATE ledger_statement_lines "
                "   SET match_status='VOUCHER_CREATED', "
                "       matched_voucher_line_id=?, "
                "       resolved_at=datetime('now'), "
                "       resolved_by_user_id=? "
                " WHERE id=?",
                (vl_id, user_id, statement_line_id),
            )
            self.db.execute(
                "UPDATE voucher_lines "
                "   SET party_cleared_date=?, "
                "       ledger_statement_line_id=?, "
                "       party_cleared_by_user_id=? "
                " WHERE id=?",
                (sl["txn_date"], statement_line_id, user_id, vl_id),
            )

    def mark_book_line_cleared(
        self, voucher_line_id: int, as_of_date: str,
        user_id: int | None = None,
    ) -> None:
        with self.db:
            self.db.execute(
                "UPDATE voucher_lines "
                "   SET party_cleared_date=?, party_cleared_by_user_id=? "
                " WHERE id=?",
                (as_of_date, user_id, voucher_line_id),
            )

    def mark_ignored(
        self, statement_line_id: int, user_id: int | None = None,
        note: str = "",
    ) -> None:
        with self.db:
            self.db.execute(
                "UPDATE ledger_statement_lines "
                "   SET match_status='IGNORED', "
                "       resolved_at=datetime('now'), "
                "       resolved_by_user_id=?, "
                "       notes=? "
                " WHERE id=?",
                (user_id, note or None, statement_line_id),
            )

    def flag(
        self, statement_line_id: int, note: str,
        user_id: int | None = None,
    ) -> None:
        with self.db:
            self.db.execute(
                "UPDATE ledger_statement_lines "
                "   SET match_status='FLAGGED', "
                "       resolved_at=datetime('now'), "
                "       resolved_by_user_id=?, "
                "       notes=? "
                " WHERE id=?",
                (user_id, note, statement_line_id),
            )

    # ── Finalise / history ────────────────────────────────────────────────────

    def finalise(
        self, statement_id: int, user_id: int | None = None,
        notes: str = "",
    ) -> int:
        stmt = self.db.execute(
            "SELECT ledger_id, period_from, period_to, "
            "       statement_closing FROM ledger_statements WHERE id=?",
            (statement_id,),
        ).fetchone()
        if not stmt:
            raise ValueError(f"Statement {statement_id} not found.")
        ledger_id = stmt["ledger_id"]
        period_to = stmt["period_to"]
        book_balance = self._book_balance(ledger_id, period_to)
        statement_balance = (
            stmt["statement_closing"]
            if stmt["statement_closing"] is not None
            else book_balance
        )
        counts = self.db.execute(
            """SELECT
                 SUM(CASE WHEN match_status IN ('AUTO_MATCHED','MANUAL_MATCHED','VOUCHER_CREATED')
                          THEN 1 ELSE 0 END) AS matched,
                 SUM(CASE WHEN match_status IN ('UNMATCHED','FLAGGED','IGNORED')
                          THEN 1 ELSE 0 END) AS unmatched_stmt
                 FROM ledger_statement_lines
                WHERE statement_id=?""",
            (statement_id,),
        ).fetchone()
        matched_count = counts["matched"] or 0
        unmatched_stmt_count = counts["unmatched_stmt"] or 0
        unmatched_book_count = self.db.execute(
            """SELECT COUNT(*) AS c
                 FROM voucher_lines vl
                 JOIN vouchers v ON v.id = vl.voucher_id
                WHERE vl.ledger_id = ? AND v.is_cancelled = 0
                  AND v.company_id = ?
                  AND v.voucher_date BETWEEN ? AND ?
                  AND (vl.party_cleared_date IS NULL OR vl.party_cleared_date = '')""",
            (ledger_id, self.company_id, stmt["period_from"], period_to),
        ).fetchone()["c"]
        with self.db:
            cur = self.db.execute(
                """INSERT INTO ledger_reconciliations
                   (company_id, ledger_id, statement_id, as_of_date,
                    book_balance, statement_balance,
                    matched_count, unmatched_stmt_count, unmatched_book_count,
                    reconciled_by_user_id, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.company_id, ledger_id, statement_id, period_to,
                    book_balance, statement_balance,
                    matched_count, unmatched_stmt_count, unmatched_book_count,
                    user_id, notes or None,
                ),
            )
        return cur.lastrowid

    def history_for_ledger(self, ledger_id: int) -> list[dict]:
        rows = self.db.execute(
            """SELECT id, statement_id, as_of_date, book_balance,
                      statement_balance,
                      matched_count, unmatched_stmt_count, unmatched_book_count,
                      finalised_at, notes
                 FROM ledger_reconciliations
                WHERE company_id=? AND ledger_id=?
             ORDER BY as_of_date DESC, finalised_at DESC""",
            (self.company_id, ledger_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_imports(self, ledger_id: int) -> list[dict]:
        rows = self.db.execute(
            """SELECT ls.id, ls.file_name, ls.period_from, ls.period_to,
                      ls.sign_mode, ls.import_method, ls.imported_at,
                      (SELECT COUNT(*) FROM ledger_statement_lines
                          WHERE statement_id=ls.id) AS total_lines,
                      (SELECT COUNT(*) FROM ledger_statement_lines
                          WHERE statement_id=ls.id
                            AND match_status IN ('AUTO_MATCHED','MANUAL_MATCHED','VOUCHER_CREATED'))
                          AS matched,
                      (SELECT COUNT(*) FROM ledger_statement_lines
                          WHERE statement_id=ls.id AND match_status='UNMATCHED')
                          AS unmatched,
                      (SELECT COUNT(*) FROM ledger_statement_lines
                          WHERE statement_id=ls.id
                            AND match_status IN ('IGNORED','FLAGGED'))
                          AS resolved_other,
                      (SELECT COUNT(*) FROM ledger_reconciliations
                          WHERE statement_id=ls.id) AS finalised
                 FROM ledger_statements ls
                WHERE ls.company_id=? AND ls.ledger_id=?
             ORDER BY ls.imported_at DESC""",
            (self.company_id, ledger_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_statement(
        self, statement_id: int, user_id: int | None = None,
    ) -> None:
        finalised = self.db.execute(
            "SELECT COUNT(*) AS c FROM ledger_reconciliations WHERE statement_id=?",
            (statement_id,),
        ).fetchone()
        if finalised and finalised["c"]:
            raise ValueError(
                f"This statement is referenced by {finalised['c']} "
                "finalised reconciliation(s). Delete the snapshot(s) first."
            )
        with self.db:
            self.db.execute(
                """UPDATE voucher_lines
                      SET party_cleared_date=NULL,
                          ledger_statement_line_id=NULL,
                          party_cleared_by_user_id=NULL
                    WHERE ledger_statement_line_id IN
                          (SELECT id FROM ledger_statement_lines
                            WHERE statement_id=?)""",
                (statement_id,),
            )
            self.db.execute(
                "DELETE FROM ledger_statements WHERE id=?",
                (statement_id,),
            )

    def last_party_cleared_date(self, ledger_id: int) -> str | None:
        """For auto-defaulting the next reconciliation's from-date."""
        candidates: list[str] = []
        row = self.db.execute(
            """SELECT MAX(vl.party_cleared_date) AS last
                 FROM voucher_lines vl
                 JOIN vouchers v ON v.id = vl.voucher_id
                WHERE vl.ledger_id = ? AND v.is_cancelled = 0
                  AND v.company_id = ?
                  AND vl.party_cleared_date IS NOT NULL
                  AND vl.party_cleared_date <> ''""",
            (ledger_id, self.company_id),
        ).fetchone()
        if row and row["last"]:
            candidates.append(row["last"])
        row = self.db.execute(
            """SELECT MAX(lsl.txn_date) AS last
                 FROM ledger_statement_lines lsl
                 JOIN ledger_statements ls ON ls.id = lsl.statement_id
                WHERE ls.ledger_id = ?
                  AND ls.company_id = ?
                  AND lsl.match_status='IGNORED'""",
            (ledger_id, self.company_id),
        ).fetchone()
        if row and row["last"]:
            candidates.append(row["last"])
        if candidates:
            return max(candidates)
        row = self.db.execute(
            """SELECT MAX(as_of_date) AS last FROM ledger_reconciliations
                WHERE ledger_id=? AND company_id=?""",
            (ledger_id, self.company_id),
        ).fetchone()
        return row["last"] if row and row["last"] else None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _reapply_period(
        self,
        statement_id: int,
        period_from: str | None,
        period_to: str | None,
        sign_mode: str,
        user_id: int | None,
    ) -> int:
        cur = self.db.execute(
            "SELECT period_from, period_to, sign_mode FROM ledger_statements WHERE id=?",
            (statement_id,),
        ).fetchone()
        if not cur:
            return statement_id
        new_from = period_from or cur["period_from"]
        new_to   = period_to   or cur["period_to"]
        new_mode = sign_mode or cur["sign_mode"]
        if (new_from == cur["period_from"] and new_to == cur["period_to"]
                and new_mode == cur["sign_mode"]):
            return statement_id
        with self.db:
            # Unlink AUTO_MATCHED book lines outside the new range
            self.db.execute(
                """UPDATE voucher_lines
                      SET party_cleared_date=NULL,
                          ledger_statement_line_id=NULL,
                          party_cleared_by_user_id=NULL
                    WHERE id IN (
                        SELECT matched_voucher_line_id
                          FROM ledger_statement_lines
                         WHERE statement_id=?
                           AND match_status='AUTO_MATCHED'
                           AND (txn_date < ? OR txn_date > ?)
                    )""",
                (statement_id, new_from, new_to),
            )
            self.db.execute(
                "DELETE FROM ledger_statement_lines "
                " WHERE statement_id=? AND match_status='AUTO_MATCHED' "
                "   AND (txn_date < ? OR txn_date > ?)",
                (statement_id, new_from, new_to),
            )
            self.db.execute(
                "DELETE FROM ledger_statement_lines "
                " WHERE statement_id=? AND match_status='UNMATCHED' "
                "   AND (txn_date < ? OR txn_date > ?)",
                (statement_id, new_from, new_to),
            )
            # Reset still-in-range AUTO_MATCHED so auto-match re-runs
            self.db.execute(
                """UPDATE voucher_lines
                      SET party_cleared_date=NULL,
                          ledger_statement_line_id=NULL,
                          party_cleared_by_user_id=NULL
                    WHERE id IN (
                        SELECT matched_voucher_line_id
                          FROM ledger_statement_lines
                         WHERE statement_id=? AND match_status='AUTO_MATCHED'
                    )""",
                (statement_id,),
            )
            self.db.execute(
                "UPDATE ledger_statement_lines "
                "   SET match_status='UNMATCHED', "
                "       matched_voucher_line_id=NULL, "
                "       resolved_at=NULL, "
                "       resolved_by_user_id=NULL "
                " WHERE statement_id=? AND match_status='AUTO_MATCHED'",
                (statement_id,),
            )
            self.db.execute(
                "UPDATE ledger_statements "
                "   SET period_from=?, period_to=?, sign_mode=? "
                " WHERE id=?",
                (new_from, new_to, new_mode, statement_id),
            )
        return statement_id

    def _persist_statement(
        self,
        ledger_id: int,
        file_name: str,
        file_hash: str,
        period_from: str,
        period_to: str,
        statement_opening: float | None,
        statement_closing: float | None,
        sign_mode: str,
        import_method: str,
        imported_by_user_id: int | None,
        raw_meta: str,
        lines: list[dict],
    ) -> int:
        with self.db:
            cur = self.db.execute(
                """INSERT INTO ledger_statements
                   (company_id, ledger_id, file_name, file_hash,
                    period_from, period_to, statement_opening, statement_closing,
                    sign_mode, import_method, imported_by_user_id, raw_meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.company_id, ledger_id, file_name, file_hash,
                    period_from, period_to, statement_opening, statement_closing,
                    sign_mode, import_method, imported_by_user_id, raw_meta,
                ),
            )
            statement_id = cur.lastrowid
            self.db.executemany(
                """INSERT INTO ledger_statement_lines
                   (statement_id, line_index, txn_date, amount, sign,
                    narration, reference, raw_extracted)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [
                    (statement_id, l["line_index"], l["txn_date"],
                     l["amount"], l["sign"], l["narration"],
                     l["reference"], l["raw_extracted"])
                    for l in lines
                ],
            )
        return statement_id

    @staticmethod
    def _lines_from_parsed(parsed_lines: list[dict]) -> list[dict]:
        out: list[dict] = []
        for ln in parsed_lines:
            out.append({
                "line_index":    ln["line_index"],
                "txn_date":      ln["txn_date"],
                "amount":        round(float(ln["amount"]), 2),
                "sign":          ln["sign"],
                "narration":     ln.get("narration", ""),
                "reference":     ln.get("reference", ""),
                "raw_extracted": json.dumps({"raw_row": ln.get("raw_row")}),
            })
        return out

    @staticmethod
    def _resolve_period(
        lines: list[dict],
        user_from: str | None,
        user_to: str | None,
        detected_from: str | None,
        detected_to: str | None,
    ) -> tuple[str, str]:
        if not lines:
            raise ValueError("No transaction rows could be parsed.")
        if user_from or user_to:
            lo = user_from or detected_from or min(l["txn_date"] for l in lines)
            hi = user_to   or detected_to   or max(l["txn_date"] for l in lines)
            kept = [l for l in lines if lo <= l["txn_date"] <= hi]
            if not kept:
                raise ValueError(
                    "No transaction rows fell within the selected period "
                    f"({lo} to {hi})."
                )
            lines.clear()
            lines.extend(kept)
            return lo, hi
        return (
            detected_from or min(l["txn_date"] for l in lines),
            detected_to   or max(l["txn_date"] for l in lines),
        )

    def _book_balance(self, ledger_id: int, as_of_date: str) -> float:
        row = self.db.execute(
            """SELECT COALESCE(l.opening_balance, 0) AS opening,
                      COALESCE(l.opening_type, 'Dr') AS opening_type
               FROM ledgers l WHERE l.id=?""",
            (ledger_id,),
        ).fetchone()
        opening = (row["opening"] or 0.0) if row else 0.0
        if row and row["opening_type"] == "Cr":
            opening = -opening
        agg = self.db.execute(
            """SELECT COALESCE(SUM(vl.dr_amount),0) AS dr,
                      COALESCE(SUM(vl.cr_amount),0) AS cr
                 FROM voucher_lines vl
                 JOIN vouchers v ON v.id = vl.voucher_id
                WHERE vl.ledger_id=?
                  AND v.is_cancelled=0
                  AND v.company_id=?
                  AND v.voucher_date <= ?""",
            (ledger_id, self.company_id, as_of_date),
        ).fetchone()
        return round(opening + (agg["dr"] - agg["cr"]), 2)

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
