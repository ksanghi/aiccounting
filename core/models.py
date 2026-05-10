"""
Database Models — Indian Accounting System
Uses SQLite via Python's built-in sqlite3.
One .db file per company, stored in data/companies/
"""
import sqlite3
import os
from pathlib import Path
from datetime import date, datetime


DB_DIR = Path(__file__).parent.parent / "data" / "companies"
DB_DIR.mkdir(parents=True, exist_ok=True)


# ─── Schema DDL ───────────────────────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ── Company ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    gstin       TEXT,
    pan         TEXT,
    state_code  TEXT NOT NULL DEFAULT '07',   -- 2-digit GST state code
    address     TEXT,
    fy_start    TEXT NOT NULL DEFAULT '04-01', -- MM-DD
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Users ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    username    TEXT NOT NULL,
    password    TEXT NOT NULL,             -- bcrypt hash
    role        TEXT NOT NULL DEFAULT 'ACCOUNTANT',  -- ADMIN / ACCOUNTANT / VIEWER
    active      INTEGER NOT NULL DEFAULT 1,
    UNIQUE(company_id, username)
);

-- ── Account Groups (like Tally groups) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS account_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    name        TEXT NOT NULL,
    parent_id   INTEGER REFERENCES account_groups(id),
    nature      TEXT NOT NULL,  -- ASSET / LIABILITY / INCOME / EXPENSE
    affects_gross_profit INTEGER NOT NULL DEFAULT 0,  -- 1 for trading account items
    UNIQUE(company_id, name)
);

-- ── Ledger Accounts ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ledgers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    group_id        INTEGER NOT NULL REFERENCES account_groups(id),
    name            TEXT NOT NULL,
    code            TEXT,               -- optional account code
    opening_balance REAL NOT NULL DEFAULT 0.0,
    opening_type    TEXT NOT NULL DEFAULT 'Dr',  -- Dr / Cr
    -- Party fields
    gstin           TEXT,
    pan             TEXT,
    state_code      TEXT,
    is_tds_applicable INTEGER NOT NULL DEFAULT 0,
    tds_section     TEXT,               -- 194C, 194H, 194I, 194J ...
    tds_rate        REAL,
    -- Bank fields
    bank_name       TEXT,
    account_number  TEXT,
    ifsc            TEXT,
    -- System flags
    is_bank         INTEGER NOT NULL DEFAULT 0,
    is_cash         INTEGER NOT NULL DEFAULT 0,
    is_gst_ledger   INTEGER NOT NULL DEFAULT 0,
    gst_type        TEXT,               -- CGST / SGST / IGST / CESS
    is_system       INTEGER NOT NULL DEFAULT 0,  -- system-created, cannot delete
    active          INTEGER NOT NULL DEFAULT 1,
    UNIQUE(company_id, name)
);

-- ── Voucher Series ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS voucher_series (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    voucher_type TEXT NOT NULL,          -- PAYMENT / RECEIPT / JOURNAL / CONTRA / SALES / PURCHASE / DEBIT_NOTE / CREDIT_NOTE
    prefix      TEXT NOT NULL DEFAULT '',
    last_number INTEGER NOT NULL DEFAULT 0,
    fy          TEXT NOT NULL,           -- e.g. 2025-26
    UNIQUE(company_id, voucher_type, fy)
);

-- ── Vouchers (header) ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vouchers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    voucher_type    TEXT NOT NULL,
    voucher_number  TEXT NOT NULL,
    voucher_date    TEXT NOT NULL,      -- ISO date YYYY-MM-DD
    narration       TEXT,
    reference       TEXT,               -- bill ref, cheque no, etc.
    total_amount    REAL NOT NULL DEFAULT 0.0,
    is_cancelled    INTEGER NOT NULL DEFAULT 0,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    -- Source tracking
    source          TEXT DEFAULT 'MANUAL',  -- MANUAL / AI_DOC / VERBAL
    ai_confidence   REAL,
    UNIQUE(company_id, voucher_type, voucher_number)
);

-- ── Voucher Lines (ledger entries) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS voucher_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id      INTEGER NOT NULL REFERENCES vouchers(id) ON DELETE CASCADE,
    ledger_id       INTEGER NOT NULL REFERENCES ledgers(id),
    dr_amount       REAL NOT NULL DEFAULT 0.0,
    cr_amount       REAL NOT NULL DEFAULT 0.0,
    cost_centre     TEXT,
    bill_ref        TEXT,               -- outstanding bill reference
    is_tax_line     INTEGER NOT NULL DEFAULT 0,
    tax_type        TEXT,               -- CGST / SGST / IGST / TDS
    tax_rate        REAL,
    line_narration  TEXT
);

-- ── Bill References (for outstanding tracking) ────────────────────────────────
CREATE TABLE IF NOT EXISTS bill_references (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    ledger_id       INTEGER NOT NULL REFERENCES ledgers(id),
    bill_number     TEXT NOT NULL,
    bill_date       TEXT NOT NULL,
    bill_amount     REAL NOT NULL,
    pending_amount  REAL NOT NULL,
    voucher_id      INTEGER REFERENCES vouchers(id)
);

-- ── Financial Years ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS financial_years (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    fy          TEXT NOT NULL,           -- e.g. 2025-26
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    is_closed   INTEGER NOT NULL DEFAULT 0,
    UNIQUE(company_id, fy)
);

-- ── Audit Log ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL,
    user_id     INTEGER,
    action      TEXT NOT NULL,          -- CREATE / EDIT / CANCEL / DELETE
    table_name  TEXT NOT NULL,
    record_id   INTEGER NOT NULL,
    old_data    TEXT,                   -- JSON snapshot
    new_data    TEXT,                   -- JSON snapshot
    timestamp   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Bank Reconciliation: imported statement headers ─────────────────
CREATE TABLE IF NOT EXISTS bank_statements (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id           INTEGER NOT NULL REFERENCES companies(id),
    bank_ledger_id       INTEGER NOT NULL REFERENCES ledgers(id),
    file_name            TEXT NOT NULL,
    file_hash            TEXT NOT NULL,                    -- sha256, dedup
    period_from          TEXT NOT NULL,
    period_to            TEXT NOT NULL,
    statement_opening    REAL,
    statement_closing    REAL,
    import_method        TEXT NOT NULL,                    -- 'AI' | 'CSV'
    imported_at          TEXT NOT NULL DEFAULT (datetime('now')),
    imported_by_user_id  INTEGER REFERENCES users(id),
    raw_meta             TEXT,                             -- JSON
    UNIQUE(company_id, bank_ledger_id, file_hash)
);

-- ── Bank Reconciliation: per-line staging rows ──────────────────────
CREATE TABLE IF NOT EXISTS bank_statement_lines (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id             INTEGER NOT NULL REFERENCES bank_statements(id) ON DELETE CASCADE,
    line_index               INTEGER NOT NULL,
    txn_date                 TEXT NOT NULL,
    amount                   REAL NOT NULL,                -- always positive
    sign                     TEXT NOT NULL,                -- 'DR' (out) | 'CR' (in)
    narration                TEXT,
    reference                TEXT,
    raw_extracted            TEXT,                         -- audit
    match_status             TEXT NOT NULL DEFAULT 'UNMATCHED',
                                                          -- UNMATCHED | AUTO_MATCHED |
                                                          -- MANUAL_MATCHED | VOUCHER_CREATED |
                                                          -- IGNORED | FLAGGED
    matched_voucher_line_id  INTEGER REFERENCES voucher_lines(id),
    resolved_at              TEXT,
    resolved_by_user_id      INTEGER REFERENCES users(id),
    notes                    TEXT
);

-- ── Bank Reconciliation: snapshot when user finalises ───────────────
CREATE TABLE IF NOT EXISTS bank_reconciliations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id            INTEGER NOT NULL REFERENCES companies(id),
    bank_ledger_id        INTEGER NOT NULL REFERENCES ledgers(id),
    statement_id          INTEGER REFERENCES bank_statements(id),
    as_of_date            TEXT NOT NULL,
    book_balance          REAL NOT NULL,
    statement_balance     REAL NOT NULL,
    reconciled_balance    REAL NOT NULL,
    matched_count         INTEGER NOT NULL DEFAULT 0,
    unmatched_stmt_count  INTEGER NOT NULL DEFAULT 0,
    unmatched_book_count  INTEGER NOT NULL DEFAULT 0,
    finalised_at          TEXT NOT NULL DEFAULT (datetime('now')),
    reconciled_by_user_id INTEGER REFERENCES users(id),
    notes                 TEXT
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_vouchers_date     ON vouchers(company_id, voucher_date);
CREATE INDEX IF NOT EXISTS idx_vouchers_type     ON vouchers(company_id, voucher_type);
CREATE INDEX IF NOT EXISTS idx_vlines_ledger     ON voucher_lines(ledger_id);
CREATE INDEX IF NOT EXISTS idx_vlines_voucher    ON voucher_lines(voucher_id);
CREATE INDEX IF NOT EXISTS idx_ledgers_company   ON ledgers(company_id);
CREATE INDEX IF NOT EXISTS idx_bsl_status        ON bank_statement_lines(statement_id, match_status);
CREATE INDEX IF NOT EXISTS idx_bsl_match         ON bank_statement_lines(matched_voucher_line_id);
CREATE INDEX IF NOT EXISTS idx_bstmt_ledger      ON bank_statements(company_id, bank_ledger_id);
"""


# ─── Additive-column migrations ───────────────────────────────────────────────
#
# SQLite has no `ALTER TABLE ADD COLUMN IF NOT EXISTS`, and this project has no
# migration framework. To add a *nullable* column to an existing table,
# append an entry here. _apply_additive_columns() runs on every connect and
# is idempotent: it ALTERs only when PRAGMA table_info says the column is
# missing. This is the canonical pattern — do not invent migration plumbing.

_ADDITIVE_COLUMNS = [
    ("voucher_lines", "cleared_date",            "TEXT"),
    ("voucher_lines", "bank_statement_line_id",  "INTEGER"),
    ("voucher_lines", "cleared_by_user_id",      "INTEGER"),
]


def _apply_additive_columns(conn: sqlite3.Connection) -> None:
    for table, col, ddl in _ADDITIVE_COLUMNS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vlines_cleared "
        "ON voucher_lines(ledger_id, cleared_date)"
    )


# ─── Database Connection Manager ──────────────────────────────────────────────

class Database:
    """Manages a per-company SQLite connection."""

    def __init__(self, company_slug: str):
        self.path = DB_DIR / f"{company_slug}.db"
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.path),
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
            _apply_additive_columns(self._conn)
            self._conn.commit()
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        return self.connect().execute(sql, params)

    def executemany(self, sql: str, params_list) -> sqlite3.Cursor:
        return self.connect().executemany(sql, params_list)

    def commit(self):
        self.connect().commit()

    def rollback(self):
        self.connect().rollback()

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, *_):
        if exc_type:
            self.rollback()
        else:
            self.commit()
