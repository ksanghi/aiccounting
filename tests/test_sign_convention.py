"""
Sign-convention sanity check for the bank reconciliation engine.

Locks in the bank's POV used everywhere in core/bank_reconciliation.py:

    DR on the statement = money OUT of the bank
        ↔ matches voucher_lines.cr_amount > 0   (bank ledger on the Cr side)

    CR on the statement = money INTO the bank
        ↔ matches voucher_lines.dr_amount > 0   (bank ledger on the Dr side)

If a future refactor flips this, this test breaks. Run with:

    python -m unittest tests.test_sign_convention -v
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestSignConvention(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="aicc_signtest_"))
        # Patch DB_DIR so Database writes to the temp dir, not data/companies/.
        self._patcher = patch("core.models.DB_DIR", self.tmpdir)
        self._patcher.start()

        from core.models import Database
        from core.account_tree import AccountTree
        from core.voucher_engine import VoucherEngine, VoucherDraft, VoucherLine

        self.Database     = Database
        self.AccountTree  = AccountTree
        self.VoucherDraft = VoucherDraft
        self.VoucherLine  = VoucherLine

        self.db = Database("signtest")
        self.db.connect()

        cur = self.db.execute(
            "INSERT INTO companies (name, gstin, state_code) VALUES (?,?,?)",
            ("TestCo", "", "07"),
        )
        self.company_id = cur.lastrowid
        self.db.commit()

        self.tree = AccountTree(self.db, self.company_id)
        self.tree.seed_defaults()

        # A bank ledger and two counter ledgers from the seeded chart
        self.bank_id = self.tree.add_ledger(
            "Test Bank", "Bank Accounts", is_bank=True,
            account_number="1234567890",
        )
        self.expense_id = self.tree.add_ledger(
            "Test Expense", "Indirect Expenses",
        )
        self.income_id = self.tree.add_ledger(
            "Test Income", "Other Income",
        )

        self.engine = VoucherEngine(self.db, self.company_id)

        # PAYMENT — money out of the bank (bank on Cr side)
        self.engine.post(VoucherDraft(
            voucher_type="PAYMENT",
            voucher_date="2026-04-01",
            lines=[
                VoucherLine(ledger_id=self.expense_id, dr_amount=1000.0),
                VoucherLine(ledger_id=self.bank_id,    cr_amount=1000.0),
            ],
            narration="Test payment",
        ))

        # RECEIPT — money into the bank (bank on Dr side)
        self.engine.post(VoucherDraft(
            voucher_type="RECEIPT",
            voucher_date="2026-04-02",
            lines=[
                VoucherLine(ledger_id=self.bank_id,   dr_amount=2000.0),
                VoucherLine(ledger_id=self.income_id, cr_amount=2000.0),
            ],
            narration="Test receipt",
        ))

    def tearDown(self):
        try:
            self.db.close()
        except Exception:
            pass
        self._patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dr_on_statement_matches_bank_cr_amount(self):
        """Statement DR ₹1000 should match the PAYMENT voucher's bank line (cr_amount > 0)."""
        from core.bank_reconciliation import BankReconciler

        # Synthesize a one-line statement: DR ₹1000 on the payment date
        cur = self.db.execute(
            """INSERT INTO bank_statements
               (company_id, bank_ledger_id, file_name, file_hash,
                period_from, period_to, import_method)
               VALUES (?,?,?,?,?,?,?)""",
            (self.company_id, self.bank_id, "dr.csv", "h_dr",
             "2026-04-01", "2026-04-01", "TEST"),
        )
        stmt_id = cur.lastrowid
        self.db.execute(
            """INSERT INTO bank_statement_lines
               (statement_id, line_index, txn_date, amount, sign, narration, reference)
               VALUES (?,?,?,?,?,?,?)""",
            (stmt_id, 0, "2026-04-01", 1000.0, "DR", "payment", ""),
        )
        self.db.commit()

        result = BankReconciler(self.db, self.company_id, self.tree).auto_match(stmt_id)
        self.assertEqual(
            result.matched, 1,
            "Statement DR ₹1000 did not match the PAYMENT's bank line. "
            "Sign convention may have flipped: stmt DR must match "
            "voucher_lines.cr_amount > 0 (bank on Cr side)."
        )

    def test_cr_on_statement_matches_bank_dr_amount(self):
        """Statement CR ₹2000 should match the RECEIPT voucher's bank line (dr_amount > 0)."""
        from core.bank_reconciliation import BankReconciler

        cur = self.db.execute(
            """INSERT INTO bank_statements
               (company_id, bank_ledger_id, file_name, file_hash,
                period_from, period_to, import_method)
               VALUES (?,?,?,?,?,?,?)""",
            (self.company_id, self.bank_id, "cr.csv", "h_cr",
             "2026-04-02", "2026-04-02", "TEST"),
        )
        stmt_id = cur.lastrowid
        self.db.execute(
            """INSERT INTO bank_statement_lines
               (statement_id, line_index, txn_date, amount, sign, narration, reference)
               VALUES (?,?,?,?,?,?,?)""",
            (stmt_id, 0, "2026-04-02", 2000.0, "CR", "receipt", ""),
        )
        self.db.commit()

        result = BankReconciler(self.db, self.company_id, self.tree).auto_match(stmt_id)
        self.assertEqual(
            result.matched, 1,
            "Statement CR ₹2000 did not match the RECEIPT's bank line. "
            "Sign convention may have flipped: stmt CR must match "
            "voucher_lines.dr_amount > 0 (bank on Dr side)."
        )

    def test_wrong_sign_does_not_match(self):
        """Negative test: stmt DR ₹2000 (= money out) shouldn't match a RECEIPT bank line."""
        from core.bank_reconciliation import BankReconciler

        cur = self.db.execute(
            """INSERT INTO bank_statements
               (company_id, bank_ledger_id, file_name, file_hash,
                period_from, period_to, import_method)
               VALUES (?,?,?,?,?,?,?)""",
            (self.company_id, self.bank_id, "wrong.csv", "h_wrong",
             "2026-04-02", "2026-04-02", "TEST"),
        )
        stmt_id = cur.lastrowid
        self.db.execute(
            """INSERT INTO bank_statement_lines
               (statement_id, line_index, txn_date, amount, sign, narration, reference)
               VALUES (?,?,?,?,?,?,?)""",
            (stmt_id, 0, "2026-04-02", 2000.0, "DR", "wrong-sign", ""),
        )
        self.db.commit()

        result = BankReconciler(self.db, self.company_id, self.tree).auto_match(stmt_id)
        self.assertEqual(result.matched, 0,
            "DR ₹2000 should not have matched the RECEIPT's bank line "
            "(it's a Dr-side book line; only stmt CR should match it).")


if __name__ == "__main__":
    unittest.main()
