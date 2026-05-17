"""SQLAlchemy engine, session, and Base."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from license_server.config import settings


class Base(DeclarativeBase):
    pass


_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables if missing + apply idempotent additive migrations."""
    from license_server import models  # noqa: F401  (registers models)
    Base.metadata.create_all(bind=engine)
    _apply_additive_columns()


# ── Additive-column migrations ────────────────────────────────────────────
#
# SQLAlchemy's create_all doesn't add columns to existing tables. We have no
# migration framework on the server; instead we mirror the desktop's pattern
# (core/models.py::_apply_additive_columns) — list (table, column, type_ddl,
# default_sql) and ALTER if absent. Idempotent on every startup.

_ADDITIVE_COLUMNS: list[tuple[str, str, str, str]] = [
    ("licenses", "seats_allowed", "INTEGER NOT NULL DEFAULT 3", "3"),
    # Multi-product: existing rows pre-date RWAGenie, so they're all
    # accgenie. New rows must set product explicitly via mint.
    ("licenses", "product",       "TEXT NOT NULL DEFAULT 'accgenie'", "'accgenie'"),
    ("installs",  "product",      "TEXT NOT NULL DEFAULT 'accgenie'", "'accgenie'"),
    ("orders",    "product",      "TEXT NOT NULL DEFAULT 'accgenie'", "'accgenie'"),
    # SMS wallet support (post-2026-05-17). Legacy orders are all tier_purchase.
    ("orders",    "kind",              "TEXT NOT NULL DEFAULT 'tier_purchase'", "'tier_purchase'"),
    ("orders",    "wallet_license_id", "INTEGER",                                ""),
]


def _apply_additive_columns() -> None:
    from sqlalchemy import text
    if not settings.database_url.startswith("sqlite"):
        # Other backends would need provider-specific SQL — keep it sqlite-only
        # for now (matches actual deploy on Fly.io).
        return
    with engine.begin() as conn:
        for table, col, ddl, default_sql in _ADDITIVE_COLUMNS:
            cols = {
                row[1] for row in conn.execute(
                    text(f"PRAGMA table_info({table})")
                ).fetchall()
            }
            if col not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                if default_sql:
                    conn.execute(text(
                        f"UPDATE {table} SET {col} = {default_sql} "
                        f"WHERE {col} IS NULL"
                    ))
