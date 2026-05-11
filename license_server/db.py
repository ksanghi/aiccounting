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
    """Create tables if missing. Called at app startup."""
    from license_server import models  # noqa: F401  (registers models)
    Base.metadata.create_all(bind=engine)
