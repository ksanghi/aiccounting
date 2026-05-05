"""
Chart of Accounts — Indian Standard
Seeds default groups and ledgers for a new company.
Mirrors Tally Prime's default account structure.
"""
from .models import Database


# ── Default Account Groups ─────────────────────────────────────────────────────
# (name, parent_name, nature, affects_gross_profit)
DEFAULT_GROUPS = [
    # ── ASSETS ──
    ("Capital Account",        None,                   "LIABILITY", 0),
    ("Reserves & Surplus",     "Capital Account",      "LIABILITY", 0),
    ("Loans (Liability)",      None,                   "LIABILITY", 0),
    ("Secured Loans",          "Loans (Liability)",    "LIABILITY", 0),
    ("Unsecured Loans",        "Loans (Liability)",    "LIABILITY", 0),
    ("Current Liabilities",    None,                   "LIABILITY", 0),
    ("Sundry Creditors",       "Current Liabilities",  "LIABILITY", 0),
    ("Duties & Taxes",         "Current Liabilities",  "LIABILITY", 0),
    ("Provisions",             "Current Liabilities",  "LIABILITY", 0),
    ("Fixed Assets",           None,                   "ASSET",     0),
    ("Investments",            None,                   "ASSET",     0),
    ("Current Assets",         None,                   "ASSET",     0),
    ("Stock-in-Trade",         "Current Assets",       "ASSET",     1),
    ("Sundry Debtors",         "Current Assets",       "ASSET",     0),
    ("Cash-in-Hand",           "Current Assets",       "ASSET",     0),
    ("Bank Accounts",          "Current Assets",       "ASSET",     0),
    ("Loans & Advances (A)",   "Current Assets",       "ASSET",     0),
    ("Deposits (Asset)",       "Current Assets",       "ASSET",     0),
    ("Tax Assets",             "Current Assets",       "ASSET",     0),
    # ── INCOME ──
    ("Sales Accounts",         None,                   "INCOME",    1),
    ("Other Income",           None,                   "INCOME",    0),
    ("Direct Income",          None,                   "INCOME",    1),
    # ── EXPENSES ──
    ("Purchase Accounts",      None,                   "EXPENSE",   1),
    ("Direct Expenses",        None,                   "EXPENSE",   1),
    ("Indirect Expenses",      None,                   "EXPENSE",   0),
]


# ── Default Ledgers ────────────────────────────────────────────────────────────
# (name, group_name, is_cash, is_bank, is_gst_ledger, gst_type, is_system)
DEFAULT_LEDGERS = [
    # Cash & Bank
    ("Cash",                "Cash-in-Hand",        1, 0, 0, None,    1),
    ("Bank OD Account",     "Bank Accounts",       0, 1, 0, None,    0),
    # Duties & Taxes — GST
    ("CGST",               "Duties & Taxes",       0, 0, 1, "CGST",  1),
    ("SGST/UTGST",         "Duties & Taxes",       0, 0, 1, "SGST",  1),
    ("IGST",               "Duties & Taxes",       0, 0, 1, "IGST",  1),
    ("GST Cess",           "Duties & Taxes",       0, 0, 1, "CESS",  1),
    # Input Tax Credit
    ("Input CGST",         "Tax Assets",           0, 0, 1, "CGST",  1),
    ("Input SGST/UTGST",   "Tax Assets",           0, 0, 1, "SGST",  1),
    ("Input IGST",         "Tax Assets",           0, 0, 1, "IGST",  1),
    # TDS Payable
    ("TDS Payable",        "Duties & Taxes",       0, 0, 0, None,    1),
    # Common ledgers
    ("Capital Account",    "Capital Account",      0, 0, 0, None,    1),
    ("Retained Earnings",  "Reserves & Surplus",   0, 0, 0, None,    1),
    ("Opening Stock",      "Stock-in-Trade",       0, 0, 0, None,    1),
    ("Closing Stock",      "Stock-in-Trade",       0, 0, 0, None,    1),
    ("Depreciation",       "Indirect Expenses",    0, 0, 0, None,    0),
    ("Salary",             "Indirect Expenses",    0, 0, 0, None,    0),
    ("Rent",               "Indirect Expenses",    0, 0, 0, None,    0),
    ("Interest on Loan",   "Indirect Expenses",    0, 0, 0, None,    0),
    ("Telephone & Internet","Indirect Expenses",   0, 0, 0, None,    0),
    ("Travelling Expenses","Indirect Expenses",    0, 0, 0, None,    0),
    ("Misc Expenses",      "Indirect Expenses",    0, 0, 0, None,    0),
    ("Commission Received","Other Income",         0, 0, 0, None,    0),
    ("Interest Received",  "Other Income",         0, 0, 0, None,    0),
    ("Discount Allowed",   "Direct Expenses",      0, 0, 0, None,    0),
    ("Discount Received",  "Other Income",         0, 0, 0, None,    0),
]


class AccountTree:
    """Creates and manages the chart of accounts."""

    def __init__(self, db: Database, company_id: int):
        self.db = db
        self.company_id = company_id

    def seed_defaults(self):
        """Seed default groups and ledgers for a brand new company."""
        conn = self.db.connect()

        # Insert groups (order matters — parents before children)
        group_ids: dict[str, int] = {}
        for name, parent_name, nature, agp in DEFAULT_GROUPS:
            parent_id = group_ids.get(parent_name) if parent_name else None
            cur = conn.execute(
                """INSERT OR IGNORE INTO account_groups
                   (company_id, name, parent_id, nature, affects_gross_profit)
                   VALUES (?,?,?,?,?)""",
                (self.company_id, name, parent_id, nature, agp),
            )
            # Fetch id whether newly inserted or already existed
            row = conn.execute(
                "SELECT id FROM account_groups WHERE company_id=? AND name=?",
                (self.company_id, name),
            ).fetchone()
            if row:
                group_ids[name] = row["id"]

        # Insert ledgers
        for (name, group_name, is_cash, is_bank,
             is_gst, gst_type, is_system) in DEFAULT_LEDGERS:
            gid = group_ids.get(group_name)
            if gid is None:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO ledgers
                   (company_id, group_id, name, is_cash, is_bank,
                    is_gst_ledger, gst_type, is_system)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (self.company_id, gid, name, is_cash, is_bank,
                 is_gst, gst_type, is_system),
            )
        self.db.commit()

    def get_all_ledgers(self, active_only=True) -> list[dict]:
        """Return all ledgers with their group info."""
        q = """
            SELECT l.id, l.name, l.code, l.opening_balance, l.opening_type,
                   l.is_bank, l.is_cash, l.is_gst_ledger, l.gst_type,
                   l.gstin, l.pan, l.state_code,
                   l.is_tds_applicable, l.tds_section, l.tds_rate,
                   g.name as group_name, g.nature
            FROM ledgers l
            JOIN account_groups g ON l.group_id = g.id
            WHERE l.company_id = ?
        """
        if active_only:
            q += " AND l.active = 1"
        q += " ORDER BY g.nature, g.name, l.name"
        rows = self.db.execute(q, (self.company_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_ledger_balance(self, ledger_id: int,
                           as_of: str | None = None) -> dict:
        """
        Compute running balance for a ledger.
        Returns {'balance': float, 'type': 'Dr'|'Cr'}
        """
        conn = self.db.connect()

        # Opening balance
        row = conn.execute(
            "SELECT opening_balance, opening_type FROM ledgers WHERE id=?",
            (ledger_id,)
        ).fetchone()
        ob = row["opening_balance"] if row else 0.0
        ob_type = row["opening_type"] if row else "Dr"

        # Sum of voucher lines
        q = """
            SELECT COALESCE(SUM(vl.dr_amount),0) as total_dr,
                   COALESCE(SUM(vl.cr_amount),0) as total_cr
            FROM voucher_lines vl
            JOIN vouchers v ON vl.voucher_id = v.id
            WHERE vl.ledger_id = ? AND v.is_cancelled = 0
        """
        params = [ledger_id]
        if as_of:
            q += " AND v.voucher_date <= ?"
            params.append(as_of)

        bal_row = conn.execute(q, params).fetchone()
        txn_dr = bal_row["total_dr"]
        txn_cr = bal_row["total_cr"]

        # Compute net Dr or Cr
        if ob_type == "Dr":
            net = ob + txn_dr - txn_cr
        else:
            net = -ob + txn_dr - txn_cr

        balance = abs(net)
        bal_type = "Dr" if net >= 0 else "Cr"
        return {"balance": balance, "type": bal_type}

    def add_ledger(self, name: str, group_name: str, **kwargs) -> int:
        """Add a new ledger account."""
        conn = self.db.connect()
        row = conn.execute(
            "SELECT id FROM account_groups WHERE company_id=? AND name=?",
            (self.company_id, group_name),
        ).fetchone()
        if not row:
            raise ValueError(f"Group '{group_name}' not found")
        group_id = row["id"]

        cur = conn.execute(
            """INSERT INTO ledgers
               (company_id, group_id, name, opening_balance, opening_type,
                is_bank, is_cash, gstin, pan, state_code,
                is_tds_applicable, tds_section, tds_rate,
                bank_name, account_number, ifsc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self.company_id, group_id, name,
                kwargs.get("opening_balance", 0.0),
                kwargs.get("opening_type", "Dr"),
                int(kwargs.get("is_bank", False)),
                int(kwargs.get("is_cash", False)),
                kwargs.get("gstin"),
                kwargs.get("pan"),
                kwargs.get("state_code"),
                int(kwargs.get("is_tds_applicable", False)),
                kwargs.get("tds_section"),
                kwargs.get("tds_rate"),
                kwargs.get("bank_name"),
                kwargs.get("account_number"),
                kwargs.get("ifsc"),
            ),
        )
        self.db.commit()
        return cur.lastrowid

    def get_income_ledgers(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT l.id, l.name, l.is_cash,
                      l.is_bank, g.name as group_name,
                      g.nature
               FROM ledgers l
               JOIN account_groups g ON l.group_id = g.id
               WHERE l.company_id = ?
                 AND l.active = 1
                 AND g.nature = 'INCOME'
               ORDER BY g.name, l.name""",
            (self.company_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_expense_ledgers(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT l.id, l.name, l.is_cash,
                      l.is_bank, g.name as group_name,
                      g.nature
               FROM ledgers l
               JOIN account_groups g ON l.group_id = g.id
               WHERE l.company_id = ?
                 AND l.active = 1
                 AND g.nature = 'EXPENSE'
               ORDER BY g.name, l.name""",
            (self.company_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_party_ledgers(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT l.id, l.name, l.is_cash,
                      l.is_bank, g.name as group_name,
                      g.nature
               FROM ledgers l
               JOIN account_groups g ON l.group_id = g.id
               WHERE l.company_id = ?
                 AND l.active = 1
                 AND g.name IN ('Sundry Debtors', 'Sundry Creditors')
               ORDER BY g.name, l.name""",
            (self.company_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_bank_cash_ledgers(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT l.id, l.name, l.is_cash,
                      l.is_bank, g.name as group_name,
                      g.nature
               FROM ledgers l
               JOIN account_groups g ON l.group_id = g.id
               WHERE l.company_id = ?
                 AND l.active = 1
                 AND (l.is_bank = 1 OR l.is_cash = 1)
               ORDER BY l.is_cash DESC, l.name""",
            (self.company_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_party_and_bank_cash(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT l.id, l.name, l.is_cash,
                      l.is_bank, g.name as group_name,
                      g.nature
               FROM ledgers l
               JOIN account_groups g ON l.group_id = g.id
               WHERE l.company_id = ?
                 AND l.active = 1
                 AND (
                     l.is_bank = 1
                     OR l.is_cash = 1
                     OR g.name = 'Sundry Debtors'
                     OR g.name = 'Sundry Creditors'
                     OR g.name = 'Loans & Advances (A)'
                     OR g.name = 'Capital Account'
                 )
               ORDER BY l.is_cash DESC, l.is_bank DESC,
                        g.name, l.name""",
            (self.company_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_income_group_ids(self) -> list[int]:
        rows = self.db.execute(
            """SELECT id FROM account_groups
               WHERE company_id = ? AND nature = 'INCOME'""",
            (self.company_id,)
        ).fetchall()
        return [r["id"] for r in rows]

    def get_expense_group_ids(self) -> list[int]:
        rows = self.db.execute(
            """SELECT id FROM account_groups
               WHERE company_id = ? AND nature = 'EXPENSE'""",
            (self.company_id,)
        ).fetchall()
        return [r["id"] for r in rows]
