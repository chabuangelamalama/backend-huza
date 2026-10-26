from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from tests.price_guide_helpers import make_admin, make_guide


def test_a_new_guide_gets_an_id_and_dates(session):
    guide = make_guide(session)
    assert guide.guide_id is not None
    assert guide.created_at is not None
    assert guide.updated_at is not None
    assert guide.grade is None
    assert guide.created_by is None


def test_min_price_must_be_above_zero(session):
    with pytest.raises(IntegrityError):
        make_guide(session, min_price=Decimal("0"))


def test_max_price_cannot_be_below_min_price(session):
    with pytest.raises(IntegrityError):
        make_guide(session, min_price=Decimal("60"), max_price=Decimal("30"))


def test_same_min_and_max_price_is_allowed(session):
    guide = make_guide(session, min_price=Decimal("50"), max_price=Decimal("50"))
    assert guide.min_price == guide.max_price


def test_source_is_required(session):
    with pytest.raises(IntegrityError):
        make_guide(session, source=None)


def test_source_date_is_kept(session):
    guide = make_guide(session, source_date=date(2026, 3, 15))
    session.refresh(guide)
    assert guide.source_date == date(2026, 3, 15)


def test_deleting_the_creator_keeps_the_guide(session):
    admin = make_admin(session)
    guide = make_guide(session, created_by=admin.user_id)
    session.delete(admin)
    session.flush()
    session.refresh(guide)
    assert guide.created_by is None
