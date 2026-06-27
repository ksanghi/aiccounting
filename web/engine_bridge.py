"""Thin bridge to the shared Aiccounting engine.

Every call opens the per-company SQLite books (engine `Database(slug)`),
which the engine resolves under ACCGENIE_DATA_DIR/companies/<slug>.db.
The web app never touches accounting logic directly — it goes through
VoucherEngine / ReportsEngine / AccountTree exactly like the desktop app.
"""
from __future__ import annotations

import secrets

from core.models import Database
from core.account_tree import AccountTree
from core.voucher_engine import VoucherEngine, VoucherDraft, VoucherLine  # noqa: F401
from core.reports_engine import ReportsEngine

from web.config import settings


def new_slug(display_name: str) -> str:
    """A globally-unique, filesystem-safe slug for a new books file."""
    base = "".join(c.lower() if c.isalnum() else "-" for c in display_name).strip("-")
    base = (base or "company")[:32]
    return f"{base}-{secrets.token_hex(4)}"


def open_db(slug: str) -> Database:
    db = Database(slug)
    db.connect()
    return db


def create_company(display_name: str) -> tuple[str, int]:
    """Create + seed a fresh US company. Returns (slug, company_id)."""
    slug = new_slug(display_name)
    db = Database(slug)
    conn = db.connect()
    cur = conn.execute(
        "INSERT INTO companies (name, state_code, fy_start) VALUES (?, ?, ?)",
        (display_name, "", settings.fy_start),
    )
    company_id = cur.lastrowid
    db.commit()
    AccountTree(db, company_id).seed_defaults()
    # Seed a default company user so voucher.created_by (FK -> users.id) resolves.
    # It is the first row, so its id is 1 — matching engine_for(user_id=1).
    conn.execute(
        "INSERT INTO users (company_id, username, password, role) VALUES (?, ?, ?, ?)",
        (company_id, "web", "", "ADMIN"))
    db.commit()
    return slug, company_id


def engine_for(slug: str, company_id: int, user_id: int = 1) -> VoucherEngine:
    return VoucherEngine(open_db(slug), company_id, user_id=user_id)


def reports_for(slug: str, company_id: int) -> ReportsEngine:
    return ReportsEngine(open_db(slug), company_id)


def tree_for(slug: str, company_id: int) -> AccountTree:
    return AccountTree(open_db(slug), company_id)
