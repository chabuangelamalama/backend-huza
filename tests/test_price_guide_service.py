import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

import services.price_guide as service_module
from models import PriceGuide
from models.listing import Stream, Unit
from schemas.price_guide import PriceGuideCreate, PriceGuideUpdate
from services.price_guide import _position_of as position_of
from services.price_guide import price_guide_service
from tests.price_guide_helpers import guide_values


def build_guide(**changes):
    return PriceGuide(guide_id=uuid.uuid4(), **guide_values(**changes))


def build_saved_guide(**changes):
    guide = build_guide(**changes)
    guide.created_at = datetime.now(timezone.utc)
    guide.updated_at = guide.created_at
    return guide


class FakeRepository:
    def __init__(self, *guides, best=None, fail_create=False, duplicate=None):
        self.guides = {guide.guide_id: guide for guide in guides}
        self.best = best
        self.fail_create = fail_create
        self.duplicate = duplicate
        self.added = None
        self.searched = None
        self.best_filters = None

    def create(self, db, data):
        if self.fail_create:
            raise IntegrityError("insert", {}, Exception("missing user"))
        self.added = data
        guide = PriceGuide(guide_id=uuid.uuid4(), **data)
        self.guides[guide.guide_id] = guide
        return guide

    def get(self, db, guide_id):
        return self.guides.get(guide_id)

    def search(self, db, **filters):
        self.searched = filters
        return list(self.guides.values())

    def find_best(self, db, **filters):
        self.best_filters = filters
        return self.best

    def find_duplicate(self, db, **filters):
        return self.duplicate

    def update(self, db, guide, changes):
        for name, value in changes.items():
            setattr(guide, name, value)
        return guide

    def delete(self, db, guide):
        del self.guides[guide.guide_id]


def install(monkeypatch, repository):
    monkeypatch.setattr(service_module, "price_guide_repository", repository)
    return repository


@pytest.fixture
def admin():
    return SimpleNamespace(user_id=uuid.uuid4(), role="ADMIN")


@pytest.fixture
def business_user():
    return SimpleNamespace(user_id=uuid.uuid4(), role="BUSINESS_USER")


def new_guide_data():
    return PriceGuideCreate(
        stream="SAWDUST",
        material="Pine sawdust",
        unit="KILOGRAM",
        min_price="30",
        max_price="60",
        source="Kigali market survey",
        source_date=date(2026, 1, 1),
    )


def test_create_saves_the_data_and_who_created_it(monkeypatch, admin):
    repository = install(monkeypatch, FakeRepository())
    guide = price_guide_service.create_price_guide(None, new_guide_data(), admin)
    assert repository.added["created_by"] == admin.user_id
    assert repository.added["material"] == "Pine sawdust"
    assert guide.min_price == Decimal("30")


def test_create_reports_an_unknown_user(monkeypatch, admin):
    install(monkeypatch, FakeRepository(fail_create=True))
    with pytest.raises(HTTPException) as error:
        price_guide_service.create_price_guide(None, new_guide_data(), admin)
    assert error.value.status_code == 401


def test_create_rejects_a_duplicate(monkeypatch, admin):
    install(monkeypatch, FakeRepository(duplicate=build_guide()))
    with pytest.raises(HTTPException) as error:
        price_guide_service.create_price_guide(None, new_guide_data(), admin)
    assert error.value.status_code == 409


def test_create_is_blocked_for_a_business_user(monkeypatch, business_user):
    repository = install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        price_guide_service.create_price_guide(None, new_guide_data(), business_user)
    assert error.value.status_code == 403
    assert repository.added is None


def test_get_returns_the_guide(monkeypatch, admin):
    guide = build_guide()
    install(monkeypatch, FakeRepository(guide))
    assert price_guide_service.get_price_guide(None, guide.guide_id, admin) is guide


def test_get_is_allowed_for_a_business_user(monkeypatch, business_user):
    guide = build_guide()
    install(monkeypatch, FakeRepository(guide))
    found = price_guide_service.get_price_guide(None, guide.guide_id, business_user)
    assert found is guide


def test_get_unknown_guide_is_not_found(monkeypatch, admin):
    install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        price_guide_service.get_price_guide(None, uuid.uuid4(), admin)
    assert error.value.status_code == 404


def test_get_is_blocked_for_other_roles(monkeypatch):
    guide = build_guide()
    install(monkeypatch, FakeRepository(guide))
    stranger = SimpleNamespace(user_id=uuid.uuid4(), role="GUEST")
    with pytest.raises(HTTPException) as error:
        price_guide_service.get_price_guide(None, guide.guide_id, stranger)
    assert error.value.status_code == 403


def test_list_passes_the_filters_on(monkeypatch, admin):
    repository = install(monkeypatch, FakeRepository(build_guide()))
    price_guide_service.list_price_guides(
        None, admin, stream=Stream.SAWDUST, limit=5, offset=10
    )
    assert repository.searched == {"stream": Stream.SAWDUST, "limit": 5, "offset": 10}


def test_list_is_blocked_for_other_roles(monkeypatch):
    install(monkeypatch, FakeRepository(build_guide()))
    stranger = SimpleNamespace(user_id=uuid.uuid4(), role="GUEST")
    with pytest.raises(HTTPException) as error:
        price_guide_service.list_price_guides(None, stranger)
    assert error.value.status_code == 403


def test_update_changes_only_the_given_fields(monkeypatch, admin):
    guide = build_guide()
    install(monkeypatch, FakeRepository(guide))
    price_guide_service.update_price_guide(
        None, guide.guide_id, PriceGuideUpdate(max_price="80"), admin
    )
    assert guide.max_price == Decimal("80")
    assert guide.min_price == Decimal("30")
    assert guide.material == "Pine sawdust"


def test_update_cannot_put_max_price_below_the_saved_min_price(monkeypatch, admin):
    guide = build_guide()
    install(monkeypatch, FakeRepository(guide))
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(max_price="10"), admin
        )
    assert error.value.status_code == 422


def test_update_cannot_put_min_price_above_the_saved_max_price(monkeypatch, admin):
    guide = build_guide()
    install(monkeypatch, FakeRepository(guide))
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(min_price="100"), admin
        )
    assert error.value.status_code == 422


def test_update_can_move_both_prices_together(monkeypatch, admin):
    guide = build_guide()
    install(monkeypatch, FakeRepository(guide))
    price_guide_service.update_price_guide(
        None,
        guide.guide_id,
        PriceGuideUpdate(min_price="100", max_price="120"),
        admin,
    )
    assert (guide.min_price, guide.max_price) == (Decimal("100"), Decimal("120"))


def test_update_can_clear_the_district(monkeypatch, admin):
    guide = build_guide(district="Gasabo")
    install(monkeypatch, FakeRepository(guide))
    price_guide_service.update_price_guide(
        None, guide.guide_id, PriceGuideUpdate(district=None), admin
    )
    assert guide.district is None


def test_update_with_only_a_null_material_changes_nothing(monkeypatch, admin):
    guide = build_guide()
    install(monkeypatch, FakeRepository(guide))
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(material=None), admin
        )
    assert error.value.status_code == 400
    assert guide.material == "Pine sawdust"


def test_update_unknown_guide_is_not_found(monkeypatch, admin):
    install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, uuid.uuid4(), PriceGuideUpdate(max_price="80"), admin
        )
    assert error.value.status_code == 404


def test_update_is_blocked_for_a_business_user(monkeypatch, business_user):
    guide = build_guide()
    install(monkeypatch, FakeRepository(guide))
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(max_price="80"), business_user
        )
    assert error.value.status_code == 403


def test_delete_removes_the_guide(monkeypatch, admin):
    guide = build_guide()
    repository = install(monkeypatch, FakeRepository(guide))
    price_guide_service.delete_price_guide(None, guide.guide_id, admin)
    assert repository.guides == {}


def test_delete_unknown_guide_is_not_found(monkeypatch, admin):
    install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        price_guide_service.delete_price_guide(None, uuid.uuid4(), admin)
    assert error.value.status_code == 404


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        ("29.99", "below"),
        ("30", "within"),
        ("45", "within"),
        ("60", "within"),
        ("60.01", "above"),
    ],
)
def test_position_of_a_price(price, expected):
    assert position_of(Decimal(price), build_guide()) == expected


def test_position_is_unknown_without_a_price_or_a_guide():
    assert position_of(None, build_guide()) is None
    assert position_of(Decimal("40"), None) is None


def test_check_returns_the_guide_and_where_the_price_sits(monkeypatch, admin):
    guide = build_saved_guide()
    install(monkeypatch, FakeRepository(best=guide))
    result = price_guide_service.check_price(
        None,
        admin,
        stream=Stream.SAWDUST,
        material="pine sawdust",
        unit=Unit.KILOGRAM,
        price=Decimal("90"),
    )
    assert result.guide.guide_id == guide.guide_id
    assert result.position == "above"
    assert "above the usual range of 30 to 60" in result.message


def test_check_passes_the_grade_on(monkeypatch, admin):
    repository = install(monkeypatch, FakeRepository())
    price_guide_service.check_price(
        None,
        admin,
        stream=Stream.GLASS,
        material="Cullet",
        unit=Unit.TONNE,
        grade="Clear",
    )
    assert repository.best_filters["grade"] == "clear"


def test_check_without_a_guide_has_no_position(monkeypatch, admin):
    install(monkeypatch, FakeRepository())
    result = price_guide_service.check_price(
        None,
        admin,
        stream=Stream.GLASS,
        material="Cullet",
        unit=Unit.TONNE,
        price=Decimal("90"),
    )
    assert result.guide is None
    assert result.position is None
    assert result.message == "No price guide found for this material."


def test_check_warns_when_the_guide_is_old(monkeypatch, admin):
    old = date.today() - timedelta(days=200)
    guide = build_saved_guide(source_date=old)
    install(monkeypatch, FakeRepository(best=guide))
    result = price_guide_service.check_price(
        None, admin, stream=Stream.SAWDUST, material="Pine sawdust", unit=Unit.KILOGRAM
    )
    assert result.is_outdated is True
    assert "over 6 months old" in result.message


def test_check_does_not_warn_when_the_guide_is_recent(monkeypatch, admin):
    guide = build_saved_guide(source_date=date.today())
    install(monkeypatch, FakeRepository(best=guide))
    result = price_guide_service.check_price(
        None, admin, stream=Stream.SAWDUST, material="Pine sawdust", unit=Unit.KILOGRAM
    )
    assert result.is_outdated is False
    assert "over 6 months old" not in result.message


def test_check_is_blocked_for_other_roles(monkeypatch):
    install(monkeypatch, FakeRepository())
    stranger = SimpleNamespace(user_id=uuid.uuid4(), role="GUEST")
    with pytest.raises(HTTPException) as error:
        price_guide_service.check_price(
            None, stranger, stream=Stream.GLASS, material="Cullet", unit=Unit.TONNE
        )
    assert error.value.status_code == 403