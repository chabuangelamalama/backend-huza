import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from models import Base

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "test-only-signing-key-do-not-use-in-production")

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/huza_test",
)


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except Exception:
        pytest.skip("Test database is not available")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield db
    db.close()
    transaction.rollback()
    connection.close()
