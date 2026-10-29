import os
"""Database engine and per-request session."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


@lru_cache
def _session_factory() -> sessionmaker:
    """Caches the creation of the connection engine and session factory mappings."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")

    return sessionmaker(bind=create_engine(url, pool_pre_ping=True))


def get_db() -> Iterator[Session]:
    """Provides a transactional context boundaries generator for endpoint dependencies."""
    db = _session_factory()()
    try:
        yield db
    finally:
        db.close()

def _engine_options(url: str) -> dict:
    options: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    else:
        options.update(pool_size=5, max_overflow=10, pool_recycle=1800)
    return options


_settings = get_settings()

engine = create_engine(
    _settings.database_url, **_engine_options(_settings.database_url)
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """One session per request. Rolled back on error, always closed."""
    with SessionLocal() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise


def check_database() -> None:
    """Raises if the database cannot be reached."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
