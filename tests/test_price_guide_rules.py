import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import services.price_guide as service_module
from models.listing import Stream, Unit
from schemas.price_guide import PriceGuideCreate, PriceGuideUpdate
from services.price_guide import price_guide_service


class FakeRepository:
    def __init__(self, guide=None):
        self.guide = guide
        self.created = None

    def get(self, db, guide_id):
        return self.guide

    def find_duplicate(self, db, **kwargs):
        return None

    def create(self, db, data):
        self.created = data
        return data

    def update(self, db, guide, changes):
        return changes


def new_data(**changes):
    values = {
        "stream": Stream.SAWDUST,
        "material": "Pine sawdust",
        "unit": Unit.KILOGRAM,
        "min_price": Decimal("30"),
        "max_price": Decimal("60"),
        "source": "Market survey",
        "source_date": date.today(),
    }
    values.update(changes)
    return PriceGuideCreate(**values)


def saved_guide():
    return SimpleNamespace(
        guide_id=uuid.uuid4(),
        stream=Stream.SAWDUST,
        grade=None,
        material="Pine sawdust",
        unit=Unit.KILOGRAM,
        district=None,
        source_date=date.today(),
        min_price=Decimal("30"),
        max_price=Decimal("60"),
    )


@pytest.fixture
def admin():
    return SimpleNamespace(user_id=uuid.uuid4(), role="ADMIN")


@pytest.fixture
def seller():
    return SimpleNamespace(user_id=uuid.uuid4(), role="BUSINESS_USER")


@pytest.fixture
def repository(monkeypatch):
    repository = FakeRepository(saved_guide())
    monkeypatch.setattr(service_module, "price_guide_repository", repository)
    return repository


def test_create_rejects_a_max_price_below_the_min_price(repository, admin):
    data = new_data(min_price=Decimal("60"), max_price=Decimal("30"))
    with pytest.raises(HTTPException) as error:
        price_guide_service.create_price_guide(None, data, admin)
    assert error.value.status_code == 422
    assert error.value.detail == "Max price cannot be below min price"
    assert repository.created is None


def test_create_accepts_the_same_min_and_max_price(repository, admin):
    data = new_data(min_price=Decimal("50"), max_price=Decimal("50"))
    saved = price_guide_service.create_price_guide(None, data, admin)
    assert saved["min_price"] == saved["max_price"]


def test_create_rejects_a_date_in_the_future(repository, admin):
    tomorrow = date.today() + timedelta(days=1)
    with pytest.raises(HTTPException) as error:
        price_guide_service.create_price_guide(
            None, new_data(source_date=tomorrow), admin
        )
    assert error.value.status_code == 422
    assert error.value.detail == "Source date cannot be in the future"
    assert repository.created is None


def test_create_accepts_todays_date(repository, admin):
    saved = price_guide_service.create_price_guide(
        None, new_data(source_date=date.today()), admin
    )
    assert saved["source_date"] == date.today()


def test_a_business_user_is_refused_before_the_data_is_checked(repository, seller):
    data = new_data(min_price=Decimal("60"), max_price=Decimal("30"))
    with pytest.raises(HTTPException) as error:
        price_guide_service.create_price_guide(None, data, seller)
    assert error.value.status_code == 403


def test_update_rejects_a_date_in_the_future(repository, admin):
    tomorrow = date.today() + timedelta(days=1)
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None,
            repository.guide.guide_id,
            PriceGuideUpdate(source_date=tomorrow),
            admin,
        )
    assert error.value.status_code == 422


def test_update_rejects_a_max_price_below_the_saved_min_price(repository, admin):
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None,
            repository.guide.guide_id,
            PriceGuideUpdate(max_price=Decimal("5")),
            admin,
        )
    assert error.value.status_code == 422
    assert error.value.detail == "Max price cannot be below min price"


def test_update_rejects_a_min_price_above_the_saved_max_price(repository, admin):
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None,
            repository.guide.guide_id,
            PriceGuideUpdate(min_price=Decimal("90")),
            admin,
        )
    assert error.value.status_code == 422


def test_update_accepts_a_valid_new_range(repository, admin):
    changes = price_guide_service.update_price_guide(
        None,
        repository.guide.guide_id,
        PriceGuideUpdate(min_price=Decimal("40"), max_price=Decimal("80")),
        admin,
    )
    assert changes == {"min_price": Decimal("40"), "max_price": Decimal("80")}
