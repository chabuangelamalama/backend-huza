"""Database engine and per-request session."""

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings


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
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database() -> None:
    """Raises if the database cannot be reached."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
