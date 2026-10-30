import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.dependencies import get_mailer
from database import get_db
from main import app
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


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


@pytest.fixture
def mailer():
    return FakeMailer()


@pytest.fixture
def client(session, mailer):
    settings = Settings(
        _env_file=None,
        database_url="sqlite://",
        jwt_secret="test-secret-that-is-at-least-32-characters-long",
        max_failed_logins=3,
        lockout_minutes=15,
        environment="test",
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_mailer] = lambda: mailer
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
