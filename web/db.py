"""App database (tenancy + auth registry) — SQLAlchemy.

Holds only: users, accounts (tenants), and company_refs (the map from an
account to its engine SQLite books). The books themselves are NOT here —
they are per-company SQLite files owned by the Aiccounting engine.
"""
from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker, declarative_base

from web.config import settings

_connect_args = (
    {"check_same_thread": False}
    if settings.app_db_url.startswith("sqlite")
    else {}
)
engine = create_engine(settings.app_db_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db() -> Iterator[Session]:
    """FastAPI dependency — yields a request-scoped Session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_schema() -> None:
    """Create app tables on first run. Idempotent."""
    from web import models  # noqa: F401  (registers models on Base.metadata)
    Base.metadata.create_all(bind=engine)
