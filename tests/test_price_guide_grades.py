import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import services.price_guide as service_module
from models.listing import Stream, Unit
from models.price_guide import GRADES_BY_STREAM
from schemas.price_guide import PriceGuideCreate, PriceGuideUpdate
from services.price_guide import price_guide_service

UNIT = list(Unit)[0]


def make_payload(stream, grade):
    return {
        "stream": stream,
        "material": "Bottles",
        "grade": grade,
        "unit": UNIT,
        "min_price": Decimal("10"),
        "max_price": Decimal("20"),
        "source": "Market visit",
        "source_date": date(2026, 10, 1),
    }


class FakeRepository:
    def __init__(self, guide, duplicate=None):
        self.guide = guide
        self.duplicate = duplicate

    def get(self, db, guide_id):
        return self.guide

    def find_duplicate(self, db, **kwargs):
        return self.duplicate

    def update(self, db, guide, changes):
        return changes


def use_guide(monkeypatch, stream, grade, duplicate=None):
    guide = SimpleNamespace(
        guide_id=uuid.uuid4(),
        stream=stream,
        grade=grade,
        material="Bottles",
        unit=UNIT,
        district=None,
        source_date=date(2026, 10, 1),
        min_price=Decimal("10"),
        max_price=Decimal("20"),
    )
    monkeypatch.setattr(
        service_module, "price_guide_repository", FakeRepository(guide, duplicate)
    )
    return guide


@pytest.fixture
def admin():
    return SimpleNamespace(user_id=uuid.uuid4(), role="ADMIN")


@pytest.fixture
def business_user():
    return SimpleNamespace(user_id=uuid.uuid4(), role="BUSINESS_USER")


def test_every_stream_has_grades():
    for stream in Stream:
        assert GRADES_BY_STREAM[stream]


@pytest.mark.parametrize(
    "stream, grade",
    [
        (Stream.SAWDUST, "dry"),
        (Stream.SAWDUST, "wet"),
        (Stream.PLASTIC, "hard"),
        (Stream.PLASTIC, "soft"),
        (Stream.GARMENT_OFFCUTS, "cotton"),
        (Stream.GARMENT_OFFCUTS, "synthetic"),
        (Stream.GARMENT_OFFCUTS, "mixed"),
        (Stream.GLASS, "clear"),
        (Stream.GLASS, "amber"),
        (Stream.GLASS, "green"),
    ],
)
def test_create_accepts_valid_grade(stream, grade):
    data = PriceGuideCreate(**make_payload(stream, grade))
    assert data.grade == grade


def test_create_accepts_missing_grade():
    data = PriceGuideCreate(**make_payload(Stream.GLASS, None))
    assert data.grade is None


def test_create_lowercases_grade():
    data = PriceGuideCreate(**make_payload(Stream.GLASS, "Clear"))
    assert data.grade == "clear"


@pytest.mark.parametrize(
    "stream, grade",
    [
        (Stream.SAWDUST, "green"),
        (Stream.PLASTIC, "clear"),
        (Stream.GARMENT_OFFCUTS, "dry"),
        (Stream.GLASS, "A"),
    ],
)
def test_create_rejects_grade_from_another_stream(stream, grade):
    with pytest.raises(ValidationError) as error:
        PriceGuideCreate(**make_payload(stream, grade))
    assert "Allowed grades" in str(error.value)


def test_update_checks_grade_when_stream_is_sent():
    with pytest.raises(ValidationError):
        PriceGuideUpdate(stream=Stream.PLASTIC, grade="green")


def test_update_allows_grade_alone_in_schema():
    data = PriceGuideUpdate(grade="green")
    assert data.grade == "green"


def test_service_accepts_grade_valid_for_saved_stream(monkeypatch, admin):
    guide = use_guide(monkeypatch, Stream.GLASS, "clear")
    changes = price_guide_service.update_price_guide(
        None, guide.guide_id, PriceGuideUpdate(grade="amber"), admin
    )
    assert changes == {"grade": "amber"}


def test_service_rejects_grade_not_valid_for_saved_stream(monkeypatch, admin):
    guide = use_guide(monkeypatch, Stream.GLASS, "clear")
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(grade="hard"), admin
        )
    assert error.value.status_code == 422


def test_service_rejects_stream_change_that_breaks_saved_grade(monkeypatch, admin):
    guide = use_guide(monkeypatch, Stream.GLASS, "clear")
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(stream=Stream.PLASTIC), admin
        )
    assert error.value.status_code == 422


def test_service_allows_clearing_grade(monkeypatch, admin):
    guide = use_guide(monkeypatch, Stream.GLASS, "clear")
    changes = price_guide_service.update_price_guide(
        None, guide.guide_id, PriceGuideUpdate(grade=None), admin
    )
    assert changes == {"grade": None}


def test_service_rejects_empty_update(monkeypatch, admin):
    guide = use_guide(monkeypatch, Stream.GLASS, "clear")
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(), admin
        )
    assert error.value.status_code == 400


def test_service_rejects_update_that_makes_a_duplicate(monkeypatch, admin):
    guide = use_guide(
        monkeypatch, Stream.GLASS, "clear", duplicate=SimpleNamespace()
    )
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(grade="green"), admin
        )
    assert error.value.status_code == 409


def test_business_user_cannot_update(monkeypatch, business_user):
    guide = use_guide(monkeypatch, Stream.GLASS, "clear")
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(grade="green"), business_user
        )
    assert error.value.status_code == 403


def test_business_user_cannot_delete(monkeypatch, business_user):
    guide = use_guide(monkeypatch, Stream.GLASS, "clear")
    with pytest.raises(HTTPException) as error:
        price_guide_service.delete_price_guide(None, guide.guide_id, business_user)
    assert error.value.status_code == 403


def test_other_roles_cannot_read(monkeypatch):
    guide = use_guide(monkeypatch, Stream.GLASS, "clear")
    stranger = SimpleNamespace(user_id=uuid.uuid4(), role="GUEST")
    with pytest.raises(HTTPException) as error:
        price_guide_service.get_price_guide(None, guide.guide_id, stranger)
    assert error.value.status_code == 403