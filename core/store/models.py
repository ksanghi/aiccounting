"""
Store HQ schema — a SEPARATE per-company database (`<company>_store.db`).

Comprehensive operational store data. The ONLY link to the accounts company DB
is a ledger id / posted voucher number on rows (resolved via the engine) — no
cross-database foreign keys. Out of scope by design (kept lean): product
variants, batch/expiry, serial numbers, inter-location transfers, rich
merchandising/PIM (descriptions/images beyond a basic line), and anything ERP.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

STORE_SCHEMA = """
-- ── Item categories (simple grouping; optional 1-level parent) ────────────────
CREATE TABLE IF NOT EXISTS store_categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    parent_id   INTEGER,
    created_at  TEXT    DEFAULT (datetime('now'))
);

-- ── Item catalog (operational master — cost is NOT stored here; it is the
--    weighted-average of actual receipts, derived from store_stock_movements) ──
CREATE TABLE IF NOT EXISTS store_items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    sku               TEXT    NOT NULL UNIQUE,
    barcode           TEXT,
    name              TEXT    NOT NULL,
    description       TEXT    DEFAULT '',
    category_id       INTEGER,
    brand             TEXT    DEFAULT '',
    -- units of measure: stock/sell in `unit`; buy in `purchase_unit`
    -- (1 purchase_unit = units_per_purchase × unit, e.g. 1 case = 24 pc)
    unit              TEXT    NOT NULL DEFAULT 'pc',
    purchase_unit     TEXT    DEFAULT '',
    units_per_purchase REAL   NOT NULL DEFAULT 1,
    -- pricing (selling side only; cost comes from receipts)
    sale_price        REAL    NOT NULL DEFAULT 0,
    mrp               REAL    NOT NULL DEFAULT 0,      -- printed / max retail price
    min_price         REAL    NOT NULL DEFAULT 0,      -- floor for price overrides
    -- tax (US sales tax): taxable vs exempt + a tax/HSN code for classification
    taxable           INTEGER NOT NULL DEFAULT 1,
    tax_code          TEXT    DEFAULT '',
    -- stock control
    reorder_level     REAL    NOT NULL DEFAULT 0,
    reorder_qty       REAL    NOT NULL DEFAULT 0,
    max_level         REAL    NOT NULL DEFAULT 0,
    preferred_supplier_id INTEGER,
    active            INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT    DEFAULT (datetime('now')),
    updated_at        TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_store_items_cat ON store_items(category_id, active);

-- ── Suppliers (each maps to an accounts Sundry Creditor ledger) ───────────────
CREATE TABLE IF NOT EXISTS store_suppliers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    ledger_id      INTEGER,                 -- accounts Sundry Creditor ledger (the JOINT)
    contact_person TEXT    DEFAULT '',
    phone          TEXT    DEFAULT '',
    alt_phone      TEXT    DEFAULT '',
    email          TEXT    DEFAULT '',
    website        TEXT    DEFAULT '',
    address        TEXT    DEFAULT '',
    city           TEXT    DEFAULT '',
    state          TEXT    DEFAULT '',
    postal_code    TEXT    DEFAULT '',
    country        TEXT    DEFAULT 'US',
    tax_id         TEXT    DEFAULT '',       -- supplier EIN / GSTIN
    terms          TEXT    DEFAULT '',       -- payment terms, e.g. Net 30
    lead_time_days INTEGER NOT NULL DEFAULT 0,
    bank_name      TEXT    DEFAULT '',
    bank_account   TEXT    DEFAULT '',
    bank_routing   TEXT    DEFAULT '',       -- routing / IFSC
    active         INTEGER NOT NULL DEFAULT 1,
    notes          TEXT    DEFAULT '',
    created_at     TEXT    DEFAULT (datetime('now'))
);

-- ── Customers (named accounts — each maps to a Sundry Debtor ledger) ──────────
CREATE TABLE IF NOT EXISTS store_customers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    ledger_id      INTEGER,                 -- accounts Sundry Debtor ledger (the JOINT)
    contact_person TEXT    DEFAULT '',
    phone          TEXT    DEFAULT '',
    email          TEXT    DEFAULT '',
    address        TEXT    DEFAULT '',
    city           TEXT    DEFAULT '',
    state          TEXT    DEFAULT '',
    postal_code    TEXT    DEFAULT '',
    tax_id         TEXT    DEFAULT '',
    credit_limit   REAL    NOT NULL DEFAULT 0,
    terms          TEXT    DEFAULT '',
    active          INTEGER NOT NULL DEFAULT 1,
    notes          TEXT    DEFAULT '',
    created_at     TEXT    DEFAULT (datetime('now'))
);

-- ── Stock movements (source of truth for on-hand + valuation) ─────────────────
-- qty SIGNED: + = IN (GRN/RETURN/positive ADJUST/OPENING), − = OUT (SALE/wastage/
-- PURCHASE_RETURN). unit_cost = purchase rate on IN, running average on OUT.
CREATE TABLE IF NOT EXISTS store_stock_movements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL,
    move_date   TEXT    NOT NULL,           -- YYYY-MM-DD
    qty         REAL    NOT NULL,
    unit_cost   REAL    NOT NULL DEFAULT 0,
    move_type   TEXT    NOT NULL,           -- GRN/SALE/ADJUST/OPENING/RETURN/PURCHASE_RETURN
    ref         TEXT    DEFAULT '',
    voucher_no  TEXT    DEFAULT '',          -- accounts voucher (audit link)
    note        TEXT    DEFAULT '',
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_store_mov_item ON store_stock_movements(item_id, move_date, id);

-- ── Purchasing: purchase orders ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS store_purchase_orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    po_no         TEXT    NOT NULL,
    supplier_id   INTEGER NOT NULL,
    po_date       TEXT    NOT NULL,
    expected_date TEXT    DEFAULT '',
    status        TEXT    NOT NULL DEFAULT 'OPEN',   -- OPEN/PARTIAL/RECEIVED/CANCELLED
    terms         TEXT    DEFAULT '',
    subtotal      REAL    NOT NULL DEFAULT 0,
    notes         TEXT    DEFAULT '',
    created_at    TEXT    DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS store_po_lines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id        INTEGER NOT NULL,
    item_id      INTEGER NOT NULL,
    qty          REAL    NOT NULL,
    rate         REAL    NOT NULL DEFAULT 0,
    received_qty REAL    NOT NULL DEFAULT 0
);

-- ── Purchasing: goods receipt (GRN) — stock IN + posts purchase voucher ───────
CREATE TABLE IF NOT EXISTS store_grns (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    grn_no               TEXT    NOT NULL,
    po_id                INTEGER,                       -- nullable: receive without a PO
    supplier_id          INTEGER NOT NULL,
    grn_date             TEXT    NOT NULL,
    supplier_invoice_no  TEXT    DEFAULT '',
    supplier_invoice_date TEXT   DEFAULT '',
    due_date             TEXT    DEFAULT '',
    subtotal             REAL    NOT NULL DEFAULT 0,
    total                REAL    NOT NULL DEFAULT 0,
    voucher_no           TEXT    DEFAULT '',            -- accounts purchase voucher
    notes                TEXT    DEFAULT '',
    created_at           TEXT    DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS store_grn_lines (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    grn_id  INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    qty     REAL    NOT NULL,
    rate    REAL    NOT NULL DEFAULT 0
);

-- ── Selling: counter sales / named-customer invoices / returns ────────────────
CREATE TABLE IF NOT EXISTS store_sales (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_no            TEXT    NOT NULL,
    sale_type          TEXT    NOT NULL,        -- COUNTER / INVOICE / RETURN
    customer_id        INTEGER,                 -- store customer (Type-2); null for counter
    customer_ledger_id INTEGER,                 -- accounts Sundry Debtor (Type-2)
    sale_date          TEXT    NOT NULL,
    due_date           TEXT    DEFAULT '',       -- for credit invoices
    subtotal           REAL    NOT NULL DEFAULT 0,
    discount           REAL    NOT NULL DEFAULT 0,
    tax                REAL    NOT NULL DEFAULT 0,
    total              REAL    NOT NULL DEFAULT 0,
    voucher_no         TEXT    DEFAULT '',        -- revenue voucher (invoice / day-close)
    day_closed         INTEGER NOT NULL DEFAULT 0,
    status             TEXT    NOT NULL DEFAULT 'POSTED',
    notes              TEXT    DEFAULT '',
    created_at         TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_store_sales_date ON store_sales(sale_date, sale_type, day_closed);
CREATE TABLE IF NOT EXISTS store_sale_lines (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id    INTEGER NOT NULL,
    item_id    INTEGER NOT NULL,
    qty        REAL    NOT NULL,
    unit_price REAL    NOT NULL DEFAULT 0,
    discount   REAL    NOT NULL DEFAULT 0,
    line_total REAL    NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS store_sale_tenders (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id   INTEGER NOT NULL,
    tender    TEXT    NOT NULL,                 -- CASH / CARD / UPI / ON_ACCOUNT
    amount    REAL    NOT NULL,
    reference TEXT    DEFAULT ''                -- card/UPI txn ref
);

-- ── Day close (Z report) — the daily counter-sales summary by tender ──────────
CREATE TABLE IF NOT EXISTS store_day_close (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    close_date       TEXT    NOT NULL,
    voucher_no       TEXT    DEFAULT '',
    cash_total       REAL    DEFAULT 0,
    card_total       REAL    DEFAULT 0,
    upi_total        REAL    DEFAULT 0,
    on_account_total REAL    DEFAULT 0,
    subtotal         REAL    DEFAULT 0,
    tax              REAL    DEFAULT 0,
    total            REAL    DEFAULT 0,
    created_at       TEXT    DEFAULT (datetime('now'))
);

-- ── Per-store number series ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS store_series (
    name        TEXT PRIMARY KEY,        -- PO / GRN / SALE / INV / DAY / RET / DN
    last_number INTEGER NOT NULL DEFAULT 0
);
"""


class StoreDB:
    """A separate SQLite database for one company's store data — a DISTINCT file
    from the accounts company DB. Small surface (execute/commit/close) so the
    engine reads like core.models.Database."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None

    @classmethod
    def for_company(cls, company_slug: str) -> "StoreDB":
        from core.paths import companies_dir
        return cls(Path(companies_dir()) / f"{company_slug}_store.db")

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(STORE_SCHEMA)
            self._conn.commit()
        return self._conn

    def execute(self, sql: str, params=()):
        return self.connect().execute(sql, params)

    def commit(self) -> None:
        if self._conn:
            self._conn.commit()

    def next_number(self, name: str) -> int:
        conn = self.connect()
        conn.execute("INSERT OR IGNORE INTO store_series (name, last_number) VALUES (?,0)", (name,))
        conn.execute("UPDATE store_series SET last_number = last_number + 1 WHERE name=?", (name,))
        return conn.execute("SELECT last_number FROM store_series WHERE name=?", (name,)).fetchone()[0]

    def close(self) -> None:
        if self._conn:
            self._conn.commit()
            self._conn.close()
            self._conn = None
