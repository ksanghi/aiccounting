"""
Database Models — Indian Accounting System
Uses SQLite via Python's built-in sqlite3.
One .db file per company, stored in data/companies/
"""
import sqlite3
import os
from pathlib import Path
from datetime import date, datetime

from core.paths import companies_dir


def _db_dir() -> Path:
    """
    Resolved at first call (not import time) so PyInstaller's frozen
    detection works correctly even when this module is imported very
    early during startup.
    """
    return companies_dir()


# Back-compat alias for any code reading DB_DIR directly.
DB_DIR = _db_dir()


# ─── Schema DDL ───────────────────────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ── Company ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    gstin       TEXT,
    gst_username TEXT,                         -- GST portal login username (for GSTR-2B auto-pull)
    pan         TEXT,
    tan         TEXT,                          -- Tax Deduction A/c No. (for TDS)
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
    hsn_code        TEXT,               -- default HSN/SAC for this ledger (GSTR-1 HSN summary)
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
    voucher_id      INTEGER REFERENCES vouchers(id),
    ref_type        TEXT NOT NULL DEFAULT 'BILL',   -- BILL / ADVANCE
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bill_refs_party
    ON bill_references(company_id, ledger_id, pending_amount);

-- ── Bill Allocations (bill-wise settlements: receipt/payment → bill) ──────────
CREATE TABLE IF NOT EXISTS bill_allocations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id    INTEGER NOT NULL REFERENCES companies(id),
    bill_ref_id   INTEGER REFERENCES bill_references(id),   -- NULL = on-account
    voucher_id    INTEGER NOT NULL REFERENCES vouchers(id),
    ledger_id     INTEGER NOT NULL REFERENCES ledgers(id),
    amount        REAL NOT NULL,
    alloc_type    TEXT NOT NULL DEFAULT 'AGAINST',  -- AGAINST / ON_ACCOUNT / NEW / ADVANCE
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bill_alloc_voucher
    ON bill_allocations(company_id, voucher_id);

-- ── Cash-flow expectations (assisted forecast: party → expected period) ────────
-- The user ticks which half-month period they expect each open receivable to
-- arrive / each payable to go out. Posting stays automatic; this is a separate
-- planning worksheet. One row per (party ledger, direction).
CREATE TABLE IF NOT EXISTS cashflow_expectations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id   INTEGER NOT NULL REFERENCES companies(id),
    ledger_id    INTEGER NOT NULL REFERENCES ledgers(id),
    kind         TEXT NOT NULL,            -- IN (receivable) / OUT (payable)
    period_start TEXT NOT NULL,            -- ISO date of the chosen half-month period
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(company_id, ledger_id, kind)
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

-- ── Period Locks (ad-hoc date-range locks; FY-level uses financial_years.is_closed) ──
CREATE TABLE IF NOT EXISTS period_locks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    lock_from   TEXT NOT NULL,                         -- ISO date inclusive
    lock_to     TEXT NOT NULL,                         -- ISO date inclusive
    reason      TEXT,
    locked_at   TEXT NOT NULL DEFAULT (datetime('now')),
    locked_by   INTEGER REFERENCES users(id)
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

-- ── Bank FEED connections (SimpleFIN / Plaid / Teller) ──────────────
-- Links a provider connection to an AccGenie bank ledger. One row per
-- (ledger, provider, provider-account). access_token holds the SimpleFIN
-- access URL (embedded creds) or a Plaid access_token — local per-company db
-- on the user's own machine, same trust level as other stored credentials.
CREATE TABLE IF NOT EXISTS bank_feed_connections (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id       INTEGER NOT NULL REFERENCES companies(id),
    bank_ledger_id   INTEGER NOT NULL REFERENCES ledgers(id),
    provider         TEXT NOT NULL,                 -- 'simplefin' | 'plaid' | 'teller'
    access_token     TEXT,                          -- SimpleFIN access URL / Plaid token
    feed_account_id  TEXT,                          -- provider's account id this row feeds
    label            TEXT DEFAULT '',
    last_pulled_at   TEXT,
    created_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(company_id, bank_ledger_id, provider, feed_account_id)
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

-- ── Ledger Reconciliation: imported party-statement headers ─────────
CREATE TABLE IF NOT EXISTS ledger_statements (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id           INTEGER NOT NULL REFERENCES companies(id),
    ledger_id            INTEGER NOT NULL REFERENCES ledgers(id),
    file_name            TEXT NOT NULL,
    file_hash            TEXT NOT NULL,
    period_from          TEXT NOT NULL,
    period_to            TEXT NOT NULL,
    statement_opening    REAL,
    statement_closing    REAL,
    sign_mode            TEXT NOT NULL DEFAULT 'MIRROR',  -- 'MIRROR' | 'SAME'
    import_method        TEXT NOT NULL,                   -- 'LOCAL' | 'AI'
    imported_at          TEXT NOT NULL DEFAULT (datetime('now')),
    imported_by_user_id  INTEGER REFERENCES users(id),
    raw_meta             TEXT,
    UNIQUE(company_id, ledger_id, file_hash)
);

-- ── Ledger Reconciliation: per-line staging rows ──────────────────────
CREATE TABLE IF NOT EXISTS ledger_statement_lines (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id             INTEGER NOT NULL REFERENCES ledger_statements(id) ON DELETE CASCADE,
    line_index               INTEGER NOT NULL,
    txn_date                 TEXT NOT NULL,
    amount                   REAL NOT NULL,
    sign                     TEXT NOT NULL,             -- DR/CR exactly as in the file
    narration                TEXT,
    reference                TEXT,
    raw_extracted            TEXT,
    match_status             TEXT NOT NULL DEFAULT 'UNMATCHED',
                                                        -- UNMATCHED | AUTO_MATCHED |
                                                        -- MANUAL_MATCHED | VOUCHER_CREATED |
                                                        -- IGNORED | FLAGGED
    matched_voucher_line_id  INTEGER REFERENCES voucher_lines(id),
    resolved_at              TEXT,
    resolved_by_user_id      INTEGER REFERENCES users(id),
    notes                    TEXT
);

-- ── Ledger Reconciliation: snapshot when finalised ────────────────────
CREATE TABLE IF NOT EXISTS ledger_reconciliations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id            INTEGER NOT NULL REFERENCES companies(id),
    ledger_id             INTEGER NOT NULL REFERENCES ledgers(id),
    statement_id          INTEGER REFERENCES ledger_statements(id),
    as_of_date            TEXT NOT NULL,
    book_balance          REAL NOT NULL,
    statement_balance     REAL NOT NULL,
    matched_count         INTEGER NOT NULL DEFAULT 0,
    unmatched_stmt_count  INTEGER NOT NULL DEFAULT 0,
    unmatched_book_count  INTEGER NOT NULL DEFAULT 0,
    finalised_at          TEXT NOT NULL DEFAULT (datetime('now')),
    reconciled_by_user_id INTEGER REFERENCES users(id),
    notes                 TEXT
);

-- ── Migration runs (book migration from other software) ──────────────
CREATE TABLE IF NOT EXISTS migration_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id    INTEGER NOT NULL REFERENCES companies(id),
    source_type   TEXT NOT NULL,        -- 'TALLY_XML' | 'EXCEL_COA' | 'CLOUD_CSV'
    source_label  TEXT,                 -- e.g. 'Zoho Books', 'QuickBooks', filename
    file_name     TEXT NOT NULL,
    file_hash     TEXT NOT NULL,
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at  TEXT,
    status        TEXT NOT NULL DEFAULT 'IN_PROGRESS',
                                        -- IN_PROGRESS | DRY_RUN | COMPLETED |
                                        -- FAILED | ROLLED_BACK
    counts        TEXT,                 -- JSON {groups, ledgers, vouchers, ...}
    error_log     TEXT,                 -- non-empty if failed
    notes         TEXT
);

-- ── Document Inbox (AI document processing) ──────────────────────────
-- One row per document that arrives via email / ADF scan / manual drop.
-- One watched folder is the hub; this table is the review-and-process
-- queue the accountant works through. See ai/doc_classifier.py (the
-- classify step) and core/doc_inbox.py (the store).
CREATE TABLE IF NOT EXISTS inbox_documents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id        INTEGER NOT NULL REFERENCES companies(id),
    source            TEXT NOT NULL DEFAULT 'MANUAL',  -- EMAIL | SCAN | MANUAL
    orig_name         TEXT,                            -- filename as it arrived
    stored_name       TEXT NOT NULL,                   -- nice local name on disk
    stored_path       TEXT NOT NULL,                   -- absolute path in the store
    file_hash         TEXT NOT NULL,                   -- sha256, dedup
    email_meta        TEXT,                            -- JSON: from/subject/date (EMAIL only)
    arrived_at        TEXT NOT NULL DEFAULT (datetime('now')),
    status            TEXT NOT NULL DEFAULT 'PENDING',
                                                       -- PENDING | CLASSIFIED | APPROVED |
                                                       -- POSTED | REJECTED | ERROR
    doc_type          TEXT,                            -- purchase_invoice | sales_invoice |
                                                       -- debit_note | credit_note |
                                                       -- bank_statement | other
    ai_confidence     REAL,                            -- classifier confidence 0..1
    ai_meta           TEXT,                            -- JSON: classifier reason + extracted summary
    voucher_id        INTEGER REFERENCES vouchers(id), -- set when posted as a voucher
    bank_statement_id INTEGER REFERENCES bank_statements(id),  -- set when routed to bank reco
    error             TEXT,                            -- non-empty if status=ERROR
    reviewed_by_user_id INTEGER REFERENCES users(id),
    reviewed_at       TEXT,
    notes             TEXT,
    UNIQUE(company_id, file_hash)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_inbox_status      ON inbox_documents(company_id, status);
CREATE INDEX IF NOT EXISTS idx_vouchers_date     ON vouchers(company_id, voucher_date);
CREATE INDEX IF NOT EXISTS idx_vouchers_type     ON vouchers(company_id, voucher_type);
CREATE INDEX IF NOT EXISTS idx_vlines_ledger     ON voucher_lines(ledger_id);
CREATE INDEX IF NOT EXISTS idx_vlines_voucher    ON voucher_lines(voucher_id);
CREATE INDEX IF NOT EXISTS idx_ledgers_company   ON ledgers(company_id);
CREATE INDEX IF NOT EXISTS idx_bsl_status        ON bank_statement_lines(statement_id, match_status);
CREATE INDEX IF NOT EXISTS idx_bsl_match         ON bank_statement_lines(matched_voucher_line_id);
CREATE INDEX IF NOT EXISTS idx_bstmt_ledger      ON bank_statements(company_id, bank_ledger_id);
CREATE INDEX IF NOT EXISTS idx_lsl_status        ON ledger_statement_lines(statement_id, match_status);
CREATE INDEX IF NOT EXISTS idx_lsl_match         ON ledger_statement_lines(matched_voucher_line_id);
CREATE INDEX IF NOT EXISTS idx_lstmt_ledger      ON ledger_statements(company_id, ledger_id);
CREATE INDEX IF NOT EXISTS idx_migration_company ON migration_runs(company_id, started_at);
CREATE INDEX IF NOT EXISTS idx_period_locks_company ON period_locks(company_id, lock_from, lock_to);

-- Document-AI vendor cache (A4): remembers the ledger mapping the user
-- accepted for each vendor, so repeat invoices auto-fill. See core/vendor_memory.py.
CREATE TABLE IF NOT EXISTS ai_vendor_memory (
    id           INTEGER PRIMARY KEY,
    company_id   INTEGER NOT NULL,
    vendor_key   TEXT    NOT NULL,
    voucher_type TEXT    DEFAULT '',
    dr_ledger    TEXT    NOT NULL,
    cr_ledger    TEXT    NOT NULL,
    gst_rate     REAL    DEFAULT 0,
    hits         INTEGER DEFAULT 1,
    updated_at   TEXT    DEFAULT (datetime('now')),
    UNIQUE(company_id, vendor_key)
);

-- ── US Schedule C: business mileage log (standard-mileage method) ──────────────
-- A trip log, NOT a posted voucher: the standard-mileage deduction is a tax
-- figure (miles × rate), surfaced on the Schedule C report — it does not hit the
-- books. Actual car expenses (gas/repairs) are recorded as normal vouchers.
CREATE TABLE IF NOT EXISTS mileage_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    trip_date   TEXT    NOT NULL,        -- YYYY-MM-DD
    miles       REAL    NOT NULL,
    purpose     TEXT    DEFAULT '',
    vehicle     TEXT    DEFAULT '',
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mileage_company_date ON mileage_log(company_id, trip_date);
"""


# ─── Additive-column migrations ───────────────────────────────────────────────
#
# SQLite has no `ALTER TABLE ADD COLUMN IF NOT EXISTS`, and this project has no
# migration framework. To add a *nullable* column to an existing table,
# append an entry here. _apply_additive_columns() runs on every connect and
# is idempotent: it ALTERs only when PRAGMA table_info says the column is
# missing. This is the canonical pattern — do not invent migration plumbing.

_ADDITIVE_COLUMNS = [
    ("voucher_lines", "cleared_date",                  "TEXT"),
    ("voucher_lines", "bank_statement_line_id",        "INTEGER"),
    ("voucher_lines", "cleared_by_user_id",            "INTEGER"),
    ("voucher_lines", "party_cleared_date",            "TEXT"),
    ("voucher_lines", "ledger_statement_line_id",      "INTEGER"),
    ("voucher_lines", "party_cleared_by_user_id",      "INTEGER"),
    ("companies",     "tan",                           "TEXT"),
    ("companies",     "gst_username",                  "TEXT"),
    # US (Books HQ) default sales-tax rate %, chosen at company setup.
    ("companies",     "sales_tax_rate",                "REAL"),
    ("ledgers",       "hsn_code",                      "TEXT"),
    # US Schedule C line tag on expense ledgers (NULL elsewhere / for India).
    ("ledgers",       "schedule_c_line",               "TEXT"),
    # Bill-wise referencing — added to the scaffold table for existing DBs.
    # (ALTER defaults must be constant, so created_at is nullable here; fresh
    #  DBs get datetime('now') from the SCHEMA above.)
    ("bill_references", "ref_type",                    "TEXT NOT NULL DEFAULT 'BILL'"),
    ("bill_references", "created_at",                  "TEXT"),
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vlines_party_cleared "
        "ON voucher_lines(ledger_id, party_cleared_date)"
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
