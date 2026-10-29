import os
from functools import lru_cache
from typing import Iterator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@lru_cache
def _session_factory() -> sessionmaker:
    """Caches the creation of the connection engine and session factory mappings."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")

    # Leverages optimized psycopg v3 engine configuration bindings
    return sessionmaker(bind=create_engine(url, pool_pre_ping=True))


def get_db() -> Iterator[Session]:
    """Provides a transactional context boundaries generator for endpoint dependencies."""
    db = _session_factory()()
    try:
        yield db
    finally:
        db.close()
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
