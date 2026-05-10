"""
Bank Reconciliation Engine

Workflow:
    1. import_statement (local first, AI on opt-in fallback)
    2. auto_match                — 1-to-1 (date, amount, sign) matching
    3. user resolves the rest    — manual_match / create_voucher_for_line /
                                   mark_book_line_cleared / mark_ignored / flag
    4. finalise                  — snapshot into bank_reconciliations

Sign convention (bank's POV — easy to flip-bug, document inline below):
    DR on the statement = money OUT of the bank   (matches voucher_lines.cr_amount > 0)
    CR on the statement = money INTO the bank     (matches voucher_lines.dr_amount > 0)
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.models import Database
from core.account_tree import AccountTree
from core.voucher_engine import VoucherEngine, VoucherDraft, PostedVoucher
from core.local_statement_parser import LocalDocumentParser, ParseResult


# ── Exceptions the UI listens for ────────────────────────────────────────────

class ImportError(Exception):
    """Base for bank-statement import failures the UI is expected to handle."""


class LocalParseFailed(ImportError):
    """Local parser couldn't extract — UI should ask user to allow AI fallback."""
    def __init__(self, message: str, file_text: str = ""):
        super().__init__(message)
        self.file_text = file_text


class AccountMismatch(ImportError):
    """File's account number doesn't match the ledger's stored one."""
    def __init__(self, ledger_account: str, file_account: str):
        super().__init__(
            f"Statement is for account {file_account}; "
            f"the picked ledger has account {ledger_account}."
        )
        self.ledger_account = ledger_account
        self.file_account   = file_account


class AccountUnsetWithFileNumber(ImportError):
    """File has an account number; ledger doesn't. UI should offer to populate."""
    def __init__(self, file_account: str):
        super().__init__(
            "This bank ledger has no account number set, but the statement "
            f"file says it's for account {file_account}."
        )
        self.file_account = file_account


class BankNameMismatch(ImportError):
    """File's bank name doesn't match the picked ledger (no account # to fall back to)."""
    def __init__(self, ledger_name: str, file_bank_name: str):
        super().__init__(
            f"Statement looks like it's from {file_bank_name}, "
            f"but the picked ledger is '{ledger_name}'."
        )
        self.ledger_name    = ledger_name
        self.file_bank_name = file_bank_name


class UnverifiedStatement(ImportError):
    """File doesn't expose a bank name or account number — can't verify ownership."""
    def __init__(self, ledger_name: str):
        super().__init__(
            "The statement file doesn't show a recognisable bank name or "
            f"account number. Confirm it's for ledger '{ledger_name}'."
        )
        self.ledger_name = ledger_name


# ── Date parsing helpers ──────────────────────────────────────────────────────

_DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y",
    "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d", "%d %b %Y",
    "%d-%B-%Y", "%d %B %Y", "%m/%d/%Y",
]


def _parse_date(raw: str) -> str | None:
    """Return ISO YYYY-MM-DD or None if unparseable."""
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> float | None:
    """Strip Indian numeric formatting and return a float (or None)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Remove currency markers + thousand separators, keep sign + decimal
    s = re.sub(r"[^\d.\-+]", "", s.replace(",", ""))
    if not s or s in ("-", "+", "."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── Engine ────────────────────────────────────────────────────────────────────

@dataclass
class AutoMatchResult:
    matched: int
    unmatched_stmt: int
    unmatched_book: int


class BankReconciler:
    """
    Bank reconciliation orchestrator.

    Construct once per page session: BankReconciler(db, company_id, tree).
    The instance does NOT cache statement state — every call re-queries the DB,
    so it is safe to keep the page open across imports.
    """

    def __init__(self, db: Database, company_id: int, tree: AccountTree):
        self.db = db
        self.company_id = company_id
        self.tree = tree

    # ── Imports — single pipeline ─────────────────────────────────────────────

    def import_statement(
        self,
        *,
        bank_ledger_id: int,
        file_path: str,
        period_from: str | None = None,
        period_to: str | None = None,
        allow_ai: bool = False,
        api_key: str = "",
        confirm_account_population: bool = False,
        force_mismatch_override: bool = False,
        confirm_unverified: bool = False,
        user_id: int | None = None,
    ) -> int:
        """
        Single import pipeline. Tries the local heuristic parser first; on
        failure raises LocalParseFailed unless allow_ai=True (in which case
        it falls back to the paid AI parser).

        Account-number checks happen *after* a successful local parse:

        - File has account number, ledger has none →
              raises AccountUnsetWithFileNumber, unless
              `confirm_account_population=True` (sets ledger.account_number).
        - File and ledger both have account numbers but they don't match →
              raises AccountMismatch, unless `force_mismatch_override=True`.

        Returns the statement_id.
        """
        path = Path(file_path)
        if not path.exists():
            raise ValueError(f"File not found: {file_path}")

        file_hash = self._sha256(path)
        existing = self.db.execute(
            "SELECT id FROM bank_statements "
            "WHERE company_id=? AND bank_ledger_id=? AND file_hash=?",
            (self.company_id, bank_ledger_id, file_hash),
        ).fetchone()
        if existing:
            return self._reapply_period(
                existing["id"], period_from, period_to, user_id,
            )

        # ── 1. Local parse ──
        result = LocalDocumentParser().parse_bank_statement(file_path)
        if not result.success:
            if not allow_ai:
                raise LocalParseFailed(
                    result.error or "Local parser could not read the file.",
                    file_text=result.file_text,
                )
            return self._import_via_ai(
                bank_ledger_id=bank_ledger_id,
                file_path=file_path,
                file_hash=file_hash,
                api_key=api_key,
                period_from=period_from,
                period_to=period_to,
                user_id=user_id,
            )

        # ── 2. Statement-belongs-to-ledger qualification ──
        self._validate_statement_ownership(
            bank_ledger_id,
            file_account=result.account_number,
            file_bank_name=result.bank_name,
            confirm_account_population=confirm_account_population,
            force_mismatch_override=force_mismatch_override,
            confirm_unverified=confirm_unverified,
        )

        # ── 3. Build / filter lines ──
        lines = self._lines_from_parsed(result.lines)
        stmt_period_from, stmt_period_to = self._resolve_period(
            lines, period_from, period_to,
            result.period_from, result.period_to,
        )

        # ── 4. Persist ──
        return self._persist_statement(
            bank_ledger_id=bank_ledger_id,
            file_name=path.name,
            file_hash=file_hash,
            period_from=stmt_period_from,
            period_to=stmt_period_to,
            statement_opening=None,
            statement_closing=None,
            import_method="LOCAL",
            imported_by_user_id=user_id,
            raw_meta=json.dumps({
                "bank_name":      result.bank_name,
                "account_number": result.account_number,
                "detected_period": [result.period_from, result.period_to],
                "ext":            path.suffix.lower(),
            }),
            lines=lines,
        )

    # ── AI fallback (private — only reachable via import_statement(allow_ai=True)) ──

    def _import_via_ai(
        self,
        *,
        bank_ledger_id: int,
        file_path: str,
        file_hash: str,
        api_key: str,
        period_from: str | None = None,
        period_to: str | None = None,
        user_id: int | None = None,
    ) -> int:
        from ai.document_parser import DocumentParser
        from ai.voucher_ai import VoucherAI
        from ai.credit_manager import CreditManager

        if not api_key:
            raise ValueError("API key required for AI fallback.")
        path = Path(file_path)

        # Parse the document → text
        parser = DocumentParser(api_key=api_key)
        result = parser.parse(str(path))
        if not result.success:
            raise ValueError(result.error or "Document parsing failed.")

        # Charge for the local + claude pages
        cm = CreditManager()
        if not cm.can_afford(result.local_pages, result.claude_pages):
            raise ValueError(
                f"Insufficient credits. Need {result.cost_summary()}; "
                f"balance Rs.{cm.balance_paise/100:.2f}."
            )
        cm.deduct(result.local_pages, result.claude_pages, str(path))

        # Look up the bank ledger name + all ledger names
        bank_row = self.db.execute(
            "SELECT name FROM ledgers WHERE id=?", (bank_ledger_id,)
        ).fetchone()
        bank_ledger_name = bank_row["name"] if bank_row else ""
        all_ledgers = self.tree.get_all_ledgers()
        ledger_names = [l["name"] for l in all_ledgers]

        company_row = self.db.execute(
            "SELECT name FROM companies WHERE id=?", (self.company_id,)
        ).fetchone()
        company_name = company_row["name"] if company_row else ""

        # Extract statement lines (not vouchers)
        ai = VoucherAI(api_key=api_key)
        extract = ai.extract_bank_statement_lines(
            document_text=result.full_text,
            bank_ledger_name=bank_ledger_name,
            ledger_names=ledger_names,
            company_name=company_name,
        )

        ai_lines = extract.get("lines") or []
        if not ai_lines:
            raise ValueError("AI extraction returned no transaction lines.")

        lines: list[dict] = []
        for i, l in enumerate(ai_lines):
            lines.append({
                "line_index":    i,
                "txn_date":      l["txn_date"],
                "amount":        round(float(l["amount"]), 2),
                "sign":          l["sign"],
                "narration":     l.get("narration", ""),
                "reference":     l.get("reference", ""),
                "raw_extracted": json.dumps(l.get("raw_extracted") or l),
            })

        # Honour the user's chosen date range if passed.
        if period_from or period_to:
            lo = period_from or extract.get("period_from") or min(l["txn_date"] for l in lines)
            hi = period_to   or extract.get("period_to")   or max(l["txn_date"] for l in lines)
            lines = [l for l in lines if lo <= l["txn_date"] <= hi]
            if not lines:
                raise ValueError(
                    "No transaction rows fell within the selected period "
                    f"({lo} to {hi})."
                )
            stmt_period_from = lo
            stmt_period_to   = hi
        else:
            stmt_period_from = (
                extract.get("period_from")
                or min(l["txn_date"] for l in lines)
            )
            stmt_period_to = (
                extract.get("period_to")
                or max(l["txn_date"] for l in lines)
            )

        return self._persist_statement(
            bank_ledger_id=bank_ledger_id,
            file_name=path.name,
            file_hash=file_hash,
            period_from=stmt_period_from,
            period_to=stmt_period_to,
            statement_opening=extract.get("statement_opening"),
            statement_closing=extract.get("statement_closing"),
            import_method="AI",
            imported_by_user_id=user_id,
            raw_meta=json.dumps({"file_type": result.file_type}),
            lines=lines,
        )

    # ── Helpers used by import_statement ──────────────────────────────────────

    def _validate_statement_ownership(
        self,
        bank_ledger_id: int,
        *,
        file_account: str | None,
        file_bank_name: str | None,
        confirm_account_population: bool,
        force_mismatch_override: bool,
        confirm_unverified: bool,
    ) -> None:
        """
        Verify the parsed statement actually belongs to the picked ledger.
        Raises AccountMismatch / AccountUnsetWithFileNumber / BankNameMismatch
        / UnverifiedStatement as appropriate.

        Resolution priority:
          1. Account number — both sides set, match → OK; both set & differ →
             AccountMismatch; ledger empty → AccountUnsetWithFileNumber.
          2. Account number missing on file but file_bank_name detected →
             check against ledger.bank_name and ledger.name; mismatch →
             BankNameMismatch.
          3. Both missing → UnverifiedStatement (caller can confirm).
        """
        row = self.db.execute(
            "SELECT name, account_number, bank_name FROM ledgers WHERE id=?",
            (bank_ledger_id,),
        ).fetchone()
        if not row:
            return

        ledger_name      = (row["name"] or "").strip()
        ledger_account   = (row["account_number"] or "").strip()
        ledger_bank_name = (row["bank_name"] or "").strip()
        file_account     = (file_account or "").strip()
        file_bank_name   = (file_bank_name or "").strip()

        # Path 1 — account number on file
        if file_account:
            if not ledger_account:
                if not confirm_account_population:
                    raise AccountUnsetWithFileNumber(file_account)
                with self.db:
                    self.db.execute(
                        "UPDATE ledgers SET account_number=? WHERE id=?",
                        (file_account, bank_ledger_id),
                    )
                return
            if self._account_numbers_match(ledger_account, file_account):
                return
            if force_mismatch_override:
                return
            raise AccountMismatch(ledger_account, file_account)

        # Path 2 — no account number on file, but we have a bank name
        if file_bank_name:
            if self._bank_name_matches_ledger(
                file_bank_name, ledger_name, ledger_bank_name,
            ):
                return
            if force_mismatch_override:
                return
            raise BankNameMismatch(ledger_name, file_bank_name)

        # Path 3 — nothing on the file to verify against
        if confirm_unverified:
            return
        raise UnverifiedStatement(ledger_name)

    @staticmethod
    def _bank_name_matches_ledger(
        file_bank_name: str,
        ledger_name: str,
        ledger_bank_name: str,
    ) -> bool:
        """Loose substring check both directions; matches 'HDFC Bank' vs 'HDFC Current'."""
        f  = (file_bank_name or "").lower().strip()
        ln = (ledger_name or "").lower().strip()
        lb = (ledger_bank_name or "").lower().strip()
        if not f:
            return False
        if lb and (f in lb or lb in f):
            return True
        if ln and f in ln:
            return True
        first = ln.split()[0] if ln else ""
        if first and (first in f or f.startswith(first)):
            return True
        return False

    @staticmethod
    def _account_numbers_match(a: str, b: str) -> bool:
        """
        True if a and b refer to the same account. Strips non-digits from
        both, accepts equality OR last-N-digit tail match (≥4 digits) so
        masked numbers like 'XXXX1234' match the full 'XXXXXX1234'.
        """
        da = re.sub(r"\D", "", a)
        db = re.sub(r"\D", "", b)
        if not da or not db:
            return False
        if da == db:
            return True
        if len(da) >= 4 and len(db) >= 4:
            return da.endswith(db) or db.endswith(da)
        return False

    @staticmethod
    def _lines_from_parsed(parsed_lines: list[dict]) -> list[dict]:
        """
        Convert the parser's row dicts into the bank_statement_lines shape
        (with raw_extracted JSON) we persist.
        """
        out: list[dict] = []
        for ln in parsed_lines:
            out.append({
                "line_index":    ln["line_index"],
                "txn_date":      ln["txn_date"],
                "amount":        round(float(ln["amount"]), 2),
                "sign":          ln["sign"],
                "narration":     ln.get("narration", ""),
                "reference":     ln.get("reference", ""),
                "raw_extracted": json.dumps({
                    "raw_row": ln.get("raw_row"),
                }),
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
        """
        Decide the statement's stored period_from/period_to and (if the user
        passed a range) trim `lines` in place to that range.

        Priority: user > detected > min/max of the parsed lines.
        """
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

    # ── Auto-matching ─────────────────────────────────────────────────────────

    def auto_match(
        self,
        statement_id: int,
        user_id: int | None = None,
    ) -> AutoMatchResult:
        """
        Match statement lines 1-to-1 to uncleared voucher_lines on
        (date, round(amount,2), sign). First-come-first-served; conservative.
        """
        stmt = self.db.execute(
            "SELECT bank_ledger_id, period_from, period_to "
            "FROM bank_statements WHERE id=?",
            (statement_id,),
        ).fetchone()
        if not stmt:
            raise ValueError(f"Statement {statement_id} not found.")

        bank_ledger_id = stmt["bank_ledger_id"]
        period_from    = stmt["period_from"]
        period_to      = stmt["period_to"]

        stmt_lines = self.db.execute(
            "SELECT id, txn_date, amount, sign FROM bank_statement_lines "
            "WHERE statement_id=? AND match_status='UNMATCHED' "
            "ORDER BY line_index",
            (statement_id,),
        ).fetchall()

        # Candidate book lines for this bank ledger in the period, uncleared.
        book_rows = self.db.execute(
            """SELECT vl.id AS id, v.voucher_date AS voucher_date,
                      vl.dr_amount AS dr_amount, vl.cr_amount AS cr_amount
                 FROM voucher_lines vl
                 JOIN vouchers v ON v.id = vl.voucher_id
                WHERE vl.ledger_id = ?
                  AND v.is_cancelled = 0
                  AND v.company_id = ?
                  AND v.voucher_date BETWEEN ? AND ?
                  AND (vl.cleared_date IS NULL OR vl.cleared_date = '')""",
            (bank_ledger_id, self.company_id, period_from, period_to),
        ).fetchall()

        # Index: (date, round(amount,2), sign) → list of voucher_line ids.
        # Sign convention again: dr > 0 = money INTO bank = stmt 'CR'.
        index: dict[tuple, list[int]] = {}
        for r in book_rows:
            if r["dr_amount"] and r["dr_amount"] > 0:
                key = (r["voucher_date"], round(r["dr_amount"], 2), "CR")
            elif r["cr_amount"] and r["cr_amount"] > 0:
                key = (r["voucher_date"], round(r["cr_amount"], 2), "DR")
            else:
                continue
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
                    "UPDATE bank_statement_lines "
                    "   SET match_status='AUTO_MATCHED', "
                    "       matched_voucher_line_id=?, "
                    "       resolved_at=datetime('now'), "
                    "       resolved_by_user_id=? "
                    " WHERE id=?",
                    (vl_id, user_id, sl["id"]),
                )
                self.db.execute(
                    "UPDATE voucher_lines "
                    "   SET cleared_date=?, "
                    "       bank_statement_line_id=?, "
                    "       cleared_by_user_id=? "
                    " WHERE id=?",
                    (sl["txn_date"], sl["id"], user_id, vl_id),
                )
                matched += 1

        unmatched_stmt = self.db.execute(
            "SELECT COUNT(*) AS c FROM bank_statement_lines "
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
                  AND (vl.cleared_date IS NULL OR vl.cleared_date = '')""",
            (bank_ledger_id, self.company_id, period_from, period_to),
        ).fetchone()["c"]

        return AutoMatchResult(
            matched=matched,
            unmatched_stmt=unmatched_stmt,
            unmatched_book=unmatched_book,
        )

    # ── Read-side queries (for the review tabs) ───────────────────────────────

    def matched_lines(self, statement_id: int) -> list[dict]:
        rows = self.db.execute(
            """SELECT bsl.id, bsl.txn_date, bsl.amount, bsl.sign,
                      bsl.narration, bsl.reference, bsl.match_status,
                      bsl.matched_voucher_line_id,
                      v.voucher_number, v.voucher_type
                 FROM bank_statement_lines bsl
            LEFT JOIN voucher_lines vl ON vl.id = bsl.matched_voucher_line_id
            LEFT JOIN vouchers v       ON v.id  = vl.voucher_id
                WHERE bsl.statement_id=?
                  AND bsl.match_status IN ('AUTO_MATCHED','MANUAL_MATCHED','VOUCHER_CREATED')
             ORDER BY bsl.txn_date, bsl.line_index""",
            (statement_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def unmatched_statement_lines(self, statement_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, txn_date, amount, sign, narration, reference, "
            "       match_status, notes "
            "  FROM bank_statement_lines "
            " WHERE statement_id=? "
            "   AND match_status IN ('UNMATCHED','FLAGGED','IGNORED') "
            " ORDER BY txn_date, line_index",
            (statement_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def unmatched_book_lines(
        self, bank_ledger_id: int, period_from: str, period_to: str,
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
                  AND (vl.cleared_date IS NULL OR vl.cleared_date = '')
             ORDER BY v.voucher_date""",
            (bank_ledger_id, self.company_id, period_from, period_to),
        ).fetchall()
        return [dict(r) for r in rows]

    def candidate_book_lines(
        self,
        bank_ledger_id: int,
        around_date: str,
        amount: float,
        sign: str,
        days: int = 7,
        amount_tolerance: float = 1.0,
    ) -> list[dict]:
        """For the 'Find Candidate' dialog — uncleared book lines near the stmt line."""
        from datetime import date as _date, timedelta
        try:
            d = _date.fromisoformat(around_date)
        except ValueError:
            return []
        lo = (d - timedelta(days=days)).isoformat()
        hi = (d + timedelta(days=days)).isoformat()
        amt_lo = max(0.0, amount - amount_tolerance)
        amt_hi = amount + amount_tolerance

        if sign == "CR":
            amount_filter = "vl.dr_amount BETWEEN ? AND ?"
        else:
            amount_filter = "vl.cr_amount BETWEEN ? AND ?"

        rows = self.db.execute(
            f"""SELECT vl.id, v.voucher_date, v.voucher_number, v.voucher_type,
                       v.narration, vl.dr_amount, vl.cr_amount
                  FROM voucher_lines vl
                  JOIN vouchers v ON v.id = vl.voucher_id
                 WHERE vl.ledger_id = ?
                   AND v.is_cancelled = 0
                   AND v.company_id = ?
                   AND v.voucher_date BETWEEN ? AND ?
                   AND (vl.cleared_date IS NULL OR vl.cleared_date = '')
                   AND {amount_filter}
              ORDER BY v.voucher_date""",
            (bank_ledger_id, self.company_id, lo, hi, amt_lo, amt_hi),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Manual resolution actions ─────────────────────────────────────────────

    def manual_match(
        self,
        statement_line_id: int,
        voucher_line_id: int,
        user_id: int | None = None,
    ) -> None:
        with self.db:
            sl = self.db.execute(
                "SELECT txn_date FROM bank_statement_lines WHERE id=?",
                (statement_line_id,),
            ).fetchone()
            if not sl:
                raise ValueError("Statement line not found.")
            self.db.execute(
                "UPDATE bank_statement_lines "
                "   SET match_status='MANUAL_MATCHED', "
                "       matched_voucher_line_id=?, "
                "       resolved_at=datetime('now'), "
                "       resolved_by_user_id=? "
                " WHERE id=?",
                (voucher_line_id, user_id, statement_line_id),
            )
            self.db.execute(
                "UPDATE voucher_lines "
                "   SET cleared_date=?, "
                "       bank_statement_line_id=?, "
                "       cleared_by_user_id=? "
                " WHERE id=?",
                (sl["txn_date"], statement_line_id, user_id, voucher_line_id),
            )

    def unmatch(
        self,
        statement_line_id: int,
        user_id: int | None = None,
    ) -> None:
        with self.db:
            row = self.db.execute(
                "SELECT matched_voucher_line_id FROM bank_statement_lines WHERE id=?",
                (statement_line_id,),
            ).fetchone()
            if not row:
                return
            vl_id = row["matched_voucher_line_id"]
            self.db.execute(
                "UPDATE bank_statement_lines "
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
                    "   SET cleared_date=NULL, "
                    "       bank_statement_line_id=NULL, "
                    "       cleared_by_user_id=NULL "
                    " WHERE id=?",
                    (vl_id,),
                )

    def create_voucher_for_line(
        self,
        statement_line_id: int,
        bank_ledger_id: int,
        draft: VoucherDraft,
        user_id: int | None = None,
    ) -> PostedVoucher:
        """
        Post a new voucher (via VoucherEngine.post) and link the bank-side
        voucher_line back to this statement line as cleared.
        """
        engine = VoucherEngine(self.db, self.company_id, user_id=user_id)
        posted = engine.post(draft)

        # Find the bank-side voucher_line in the just-posted voucher
        vl_row = self.db.execute(
            "SELECT id FROM voucher_lines "
            " WHERE voucher_id=? AND ledger_id=? "
            " ORDER BY id LIMIT 1",
            (posted.voucher_id, bank_ledger_id),
        ).fetchone()
        if not vl_row:
            raise ValueError(
                "Posted voucher has no line for the bank ledger — cannot link."
            )
        vl_id = vl_row["id"]

        sl = self.db.execute(
            "SELECT txn_date FROM bank_statement_lines WHERE id=?",
            (statement_line_id,),
        ).fetchone()
        clear_date = sl["txn_date"] if sl else draft.voucher_date

        with self.db:
            self.db.execute(
                "UPDATE bank_statement_lines "
                "   SET match_status='VOUCHER_CREATED', "
                "       matched_voucher_line_id=?, "
                "       resolved_at=datetime('now'), "
                "       resolved_by_user_id=? "
                " WHERE id=?",
                (vl_id, user_id, statement_line_id),
            )
            self.db.execute(
                "UPDATE voucher_lines "
                "   SET cleared_date=?, "
                "       bank_statement_line_id=?, "
                "       cleared_by_user_id=? "
                " WHERE id=?",
                (clear_date, statement_line_id, user_id, vl_id),
            )
        return posted

    def mark_book_line_cleared(
        self,
        voucher_line_id: int,
        as_of_date: str,
        user_id: int | None = None,
    ) -> None:
        """For in-transit cheques etc. — clear without a statement line counterpart."""
        with self.db:
            self.db.execute(
                "UPDATE voucher_lines "
                "   SET cleared_date=?, cleared_by_user_id=? "
                " WHERE id=?",
                (as_of_date, user_id, voucher_line_id),
            )

    def mark_ignored(
        self,
        statement_line_id: int,
        user_id: int | None = None,
        note: str = "",
    ) -> None:
        with self.db:
            self.db.execute(
                "UPDATE bank_statement_lines "
                "   SET match_status='IGNORED', "
                "       resolved_at=datetime('now'), "
                "       resolved_by_user_id=?, "
                "       notes=? "
                " WHERE id=?",
                (user_id, note or None, statement_line_id),
            )

    def flag(
        self,
        statement_line_id: int,
        note: str,
        user_id: int | None = None,
    ) -> None:
        with self.db:
            self.db.execute(
                "UPDATE bank_statement_lines "
                "   SET match_status='FLAGGED', "
                "       resolved_at=datetime('now'), "
                "       resolved_by_user_id=?, "
                "       notes=? "
                " WHERE id=?",
                (user_id, note, statement_line_id),
            )

    # ── Finalise ──────────────────────────────────────────────────────────────

    def finalise(
        self,
        statement_id: int,
        user_id: int | None = None,
        notes: str = "",
    ) -> int:
        """
        Snapshot the reconciliation state into bank_reconciliations.
        Returns the new reconciliation_id.
        """
        stmt = self.db.execute(
            "SELECT bank_ledger_id, period_from, period_to, "
            "       statement_closing FROM bank_statements WHERE id=?",
            (statement_id,),
        ).fetchone()
        if not stmt:
            raise ValueError(f"Statement {statement_id} not found.")

        bank_ledger_id = stmt["bank_ledger_id"]
        period_to = stmt["period_to"]

        book_balance = self._book_balance(bank_ledger_id, period_to)
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
                 FROM bank_statement_lines
                WHERE statement_id=?""",
            (statement_id,),
        ).fetchone()
        matched_count = counts["matched"] or 0
        unmatched_stmt_count = counts["unmatched_stmt"] or 0

        unmatched_book_count = self.db.execute(
            """SELECT COUNT(*) AS c
                 FROM voucher_lines vl
                 JOIN vouchers v ON v.id = vl.voucher_id
                WHERE vl.ledger_id = ?
                  AND v.is_cancelled = 0
                  AND v.company_id = ?
                  AND v.voucher_date BETWEEN ? AND ?
                  AND (vl.cleared_date IS NULL OR vl.cleared_date = '')""",
            (bank_ledger_id, self.company_id,
             stmt["period_from"], period_to),
        ).fetchone()["c"]

        # Reconciled balance = book balance adjusted for uncleared items.
        # Conservative v1: equal to book_balance (the user resolves discrepancies
        # before finalising). Surface the gap as unmatched_*_count on the snapshot.
        reconciled_balance = book_balance

        with self.db:
            cur = self.db.execute(
                """INSERT INTO bank_reconciliations
                   (company_id, bank_ledger_id, statement_id, as_of_date,
                    book_balance, statement_balance, reconciled_balance,
                    matched_count, unmatched_stmt_count, unmatched_book_count,
                    reconciled_by_user_id, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.company_id, bank_ledger_id, statement_id, period_to,
                    book_balance, statement_balance, reconciled_balance,
                    matched_count, unmatched_stmt_count, unmatched_book_count,
                    user_id, notes or None,
                ),
            )
        return cur.lastrowid

    def last_cleared_date(self, bank_ledger_id: int) -> str | None:
        """
        ISO transaction date of the latest entry on this bank ledger that
        has been *handled* — either matched (auto/manual/voucher created /
        marked-cleared) OR ignored as a known non-issue. Used to default
        the next reconciliation's period to (last_handled + 1 day) → today.

        Looks at two sources:
            (a) voucher_lines.cleared_date for cleared book entries,
            (b) bank_statement_lines.txn_date for IGNORED statement lines
                (no voucher_line is touched on Ignore).

        Falls back to the latest finalised reconciliation's as_of_date
        (also a txn-window cutoff, not wall-clock) if nothing else matches.
        """
        candidates: list[str] = []

        # (a) Latest matched book entry (transaction date)
        row = self.db.execute(
            """SELECT MAX(vl.cleared_date) AS last
                 FROM voucher_lines vl
                 JOIN vouchers v ON v.id = vl.voucher_id
                WHERE vl.ledger_id = ?
                  AND v.is_cancelled = 0
                  AND v.company_id = ?
                  AND vl.cleared_date IS NOT NULL
                  AND vl.cleared_date <> ''""",
            (bank_ledger_id, self.company_id),
        ).fetchone()
        if row and row["last"]:
            candidates.append(row["last"])

        # (b) Latest IGNORED statement line (transaction date)
        row = self.db.execute(
            """SELECT MAX(bsl.txn_date) AS last
                 FROM bank_statement_lines bsl
                 JOIN bank_statements bs ON bs.id = bsl.statement_id
                WHERE bs.bank_ledger_id = ?
                  AND bs.company_id = ?
                  AND bsl.match_status = 'IGNORED'""",
            (bank_ledger_id, self.company_id),
        ).fetchone()
        if row and row["last"]:
            candidates.append(row["last"])

        if candidates:
            return max(candidates)

        # Fallback: latest finalised reconciliation cutoff
        row = self.db.execute(
            """SELECT MAX(as_of_date) AS last FROM bank_reconciliations
                WHERE bank_ledger_id=? AND company_id=?""",
            (bank_ledger_id, self.company_id),
        ).fetchone()
        return row["last"] if row and row["last"] else None

    def history_for_ledger(self, bank_ledger_id: int) -> list[dict]:
        rows = self.db.execute(
            """SELECT id, statement_id, as_of_date, book_balance,
                      statement_balance, reconciled_balance,
                      matched_count, unmatched_stmt_count, unmatched_book_count,
                      finalised_at, notes
                 FROM bank_reconciliations
                WHERE company_id=? AND bank_ledger_id=?
             ORDER BY as_of_date DESC, finalised_at DESC""",
            (self.company_id, bank_ledger_id),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _reapply_period(
        self,
        statement_id: int,
        period_from: str | None,
        period_to: str | None,
        user_id: int | None,
    ) -> int:
        """
        Called when an already-imported file is re-imported. If the caller
        passed a new period, update the statement row and drop stale
        UNMATCHED lines outside the new range. Keep resolved lines.
        Also unlink any AUTO_MATCHED voucher_lines whose cleared_date now
        falls outside the period — they'll be re-matched on next auto_match.
        """
        if not period_from and not period_to:
            return statement_id

        cur = self.db.execute(
            "SELECT period_from, period_to FROM bank_statements WHERE id=?",
            (statement_id,),
        ).fetchone()
        if not cur:
            return statement_id

        new_from = period_from or cur["period_from"]
        new_to   = period_to   or cur["period_to"]
        if new_from == cur["period_from"] and new_to == cur["period_to"]:
            return statement_id

        with self.db:
            # Unlink AUTO_MATCHED book lines outside the new range so they
            # become available for matching against the same date if it now
            # falls inside the range. (Leave MANUAL_MATCHED / VOUCHER_CREATED
            # / IGNORED / FLAGGED alone — those are user resolutions.)
            self.db.execute(
                """UPDATE voucher_lines
                      SET cleared_date=NULL,
                          bank_statement_line_id=NULL,
                          cleared_by_user_id=NULL
                    WHERE id IN (
                        SELECT matched_voucher_line_id
                          FROM bank_statement_lines
                         WHERE statement_id=?
                           AND match_status='AUTO_MATCHED'
                           AND (txn_date < ? OR txn_date > ?)
                    )""",
                (statement_id, new_from, new_to),
            )
            # Now drop the AUTO_MATCHED stmt-line records themselves —
            # auto_match will re-match the in-range ones.
            self.db.execute(
                "DELETE FROM bank_statement_lines "
                " WHERE statement_id=? "
                "   AND match_status='AUTO_MATCHED' "
                "   AND (txn_date < ? OR txn_date > ?)",
                (statement_id, new_from, new_to),
            )
            # Drop UNMATCHED stmt-line records outside the new range.
            self.db.execute(
                "DELETE FROM bank_statement_lines "
                " WHERE statement_id=? "
                "   AND match_status='UNMATCHED' "
                "   AND (txn_date < ? OR txn_date > ?)",
                (statement_id, new_from, new_to),
            )
            # Reset still-in-range AUTO_MATCHED rows so auto_match re-runs.
            # (Avoids stale matches if the underlying ledger changed.)
            self.db.execute(
                """UPDATE voucher_lines
                      SET cleared_date=NULL,
                          bank_statement_line_id=NULL,
                          cleared_by_user_id=NULL
                    WHERE id IN (
                        SELECT matched_voucher_line_id
                          FROM bank_statement_lines
                         WHERE statement_id=? AND match_status='AUTO_MATCHED'
                    )""",
                (statement_id,),
            )
            self.db.execute(
                "UPDATE bank_statement_lines "
                "   SET match_status='UNMATCHED', "
                "       matched_voucher_line_id=NULL, "
                "       resolved_at=NULL, "
                "       resolved_by_user_id=NULL "
                " WHERE statement_id=? AND match_status='AUTO_MATCHED'",
                (statement_id,),
            )
            self.db.execute(
                "UPDATE bank_statements "
                "   SET period_from=?, period_to=? "
                " WHERE id=?",
                (new_from, new_to, statement_id),
            )
        return statement_id

    def _persist_statement(
        self,
        bank_ledger_id: int,
        file_name: str,
        file_hash: str,
        period_from: str,
        period_to: str,
        statement_opening: float | None,
        statement_closing: float | None,
        import_method: str,
        imported_by_user_id: int | None,
        raw_meta: str,
        lines: list[dict],
    ) -> int:
        with self.db:
            cur = self.db.execute(
                """INSERT INTO bank_statements
                   (company_id, bank_ledger_id, file_name, file_hash,
                    period_from, period_to, statement_opening, statement_closing,
                    import_method, imported_by_user_id, raw_meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.company_id, bank_ledger_id, file_name, file_hash,
                    period_from, period_to, statement_opening, statement_closing,
                    import_method, imported_by_user_id, raw_meta,
                ),
            )
            statement_id = cur.lastrowid
            self.db.executemany(
                """INSERT INTO bank_statement_lines
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

    def _book_balance(self, bank_ledger_id: int, as_of_date: str) -> float:
        """
        Net Dr-Cr balance for the bank ledger up to (and including) as_of_date.
        Uncleared lines are still part of the book balance.
        """
        row = self.db.execute(
            """SELECT
                 COALESCE(l.opening_balance, 0) AS opening,
                 COALESCE(l.opening_type, 'Dr') AS opening_type
               FROM ledgers l WHERE l.id=?""",
            (bank_ledger_id,),
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
            (bank_ledger_id, self.company_id, as_of_date),
        ).fetchone()
        return round(opening + (agg["dr"] - agg["cr"]), 2)

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
