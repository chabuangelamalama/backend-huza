import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from models import Base
from models.business import ApprovalStatus, BusinessRole, PayoutNetwork
from models.enquiry import EnquiryStatus
from models.user import UserRole
from tests.test_models import (
    make_business,
    make_enquiry,
    make_listing,
    make_location,
    make_user,
)

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "test-only-signing-key-do-not-use-in-production")

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/huza_test",
)


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
    from fastapi.testclient import TestClient

    from core.config import Settings, get_settings
    from core.dependencies import get_mailer
    from database import get_db
    from main import app

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


@pytest.fixture
def world(session):
    loc = make_location(session)
    seller_b = make_business(
        session,
        loc,
        approval_status=ApprovalStatus.APPROVED,
        payout_phone="254712000111",
        payout_network=PayoutNetwork.MPESA,
    )
    buyer_b = make_business(
        session,
        loc,
        role=BusinessRole.BUYER,
        approval_status=ApprovalStatus.APPROVED,
        contact_email="b@example.ke",
    )
    other_b = make_business(
        session,
        loc,
        role=BusinessRole.BUYER,
        approval_status=ApprovalStatus.APPROVED,
        contact_email="o@example.ke",
    )
    listing = make_listing(session, seller_b, loc)
    enquiry = make_enquiry(session, listing, buyer_b, status=EnquiryStatus.AGREED)
    data = dict(
        seller=make_user(session, seller_b),
        buyer=make_user(session, buyer_b, phone="254712345678"),
        other=make_user(session, other_b, phone="254712777777"),
        admin=make_user(session, role=UserRole.ADMIN),
        seller_b=seller_b,
        buyer_b=buyer_b,
        listing=listing,
        enquiry=enquiry,
    )
    session.commit()
    return data
