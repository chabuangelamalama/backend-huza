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
