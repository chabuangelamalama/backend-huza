import uuid
from datetime import date
from decimal import Decimal

from models import PriceGuide, User
from models.business import ApprovalStatus
from models.listing import Stream, Unit
from models.user import UserRole
from tests.test_models import make_business, make_location


def guide_values(**changes):
    values = dict(
        stream=Stream.SAWDUST,
        material="Pine sawdust",
        unit=Unit.KILOGRAM,
        min_price=Decimal("30"),
        max_price=Decimal("60"),
        source="Kigali market survey",
        source_date=date(2026, 1, 1),
    )
    values.update(changes)
    return values


def make_guide(session, **changes):
    guide = PriceGuide(**guide_values(**changes))
    session.add(guide)
    session.flush()
    return guide


def make_admin(session, email="diane@huza.rw"):
    user = User(
        first_name="Diane",
        last_name="Mukamana",
        email=email,
        password_hash="x",
        user_role=UserRole.ADMIN,
    )
    session.add(user)
    session.flush()
    return user


def make_business_user(
    session, email="jean@example.rw", approval=ApprovalStatus.APPROVED
):
    business = make_business(
        session, make_location(session, osm_id=uuid.uuid4().int % 10**9)
    )
    if approval is not None:
        business.approval_status = approval
        session.flush()
    user = User(
        business_id=business.business_id,
        first_name="Jean",
        last_name="Habimana",
        email=email,
        password_hash="x",
        user_role=UserRole.BUSINESS_USER,
    )
    session.add(user)
    session.flush()
    return user
