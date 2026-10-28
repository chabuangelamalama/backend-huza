import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

import services.price_guide as service_module
from models.business import ApprovalStatus
from models.listing import Stream, Unit
from models.price_guide import PriceGuide
from schemas.price_guide import PriceGuideCreate, PriceGuideUpdate
from services.price_guide import _position_of, price_guide_service


def build_saved_guide(**changes):
    values = {
        "guide_id": uuid.uuid4(),
        "stream": Stream.SAWDUST,
        "material": "Pine sawdust",
        "grade": None,
        "unit": Unit.KILOGRAM,
        "min_price": Decimal("30"),
        "max_price": Decimal("60"),
        "source": "Market survey",
        "source_date": date(2026, 1, 15),
        "sample_size": None,
        "district": None,
        "created_by": uuid.uuid4(),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    values.update(changes)
    return PriceGuide(**values)


def new_guide_data(**changes):
    values = {
        "stream": Stream.SAWDUST,
        "material": "Pine sawdust",
        "unit": Unit.KILOGRAM,
        "min_price": "30",
        "max_price": "60",
        "source": "Market survey",
        "source_date": date(2026, 1, 15),
    }
    values.update(changes)
    return PriceGuideCreate(**values)


class FakeRepository:
    def __init__(self, guide=None, duplicate=None, best=None, approval=ApprovalStatus.APPROVED):
        self.guide = guide
        self.duplicate = duplicate
        self.best = best
        self.approval = approval
        self.created = None
        self.deleted = None
        self.search_filters = None
        self.duplicate_filters = None
        self.fail_on_create = False

    def get(self, db, guide_id):
        if self.guide is not None and self.guide.guide_id == guide_id:
            return self.guide
        return None

    def get_approval_status(self, db, user_id):
        return self.approval

    def search(self, db, **filters):
        self.search_filters = filters
        return [self.guide] if self.guide is not None else []

    def find_duplicate(self, db, **filters):
        self.duplicate_filters = filters
        return self.duplicate

    def find_best(self, db, **filters):
        return self.best

    def create(self, db, data):
        if self.fail_on_create:
            raise IntegrityError("insert", {}, Exception("bad user"))
        self.created = PriceGuide(
            guide_id=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            **data,
        )
        return self.created

    def update(self, db, db_obj, data):
        for field, value in data.items():
            setattr(db_obj, field, value)
        return db_obj

    def delete(self, db, db_obj):
        self.deleted = db_obj


def install(monkeypatch, repository):
    monkeypatch.setattr(service_module, "price_guide_repository", repository)
    return repository


@pytest.fixture
def admin():
    return SimpleNamespace(user_id=uuid.uuid4(), role="ADMIN")


@pytest.fixture
def seller():
    return SimpleNamespace(user_id=uuid.uuid4(), role="BUSINESS_USER")


def test_admin_can_view_a_guide_and_sees_who_created_it(monkeypatch, admin):
    guide = build_saved_guide()
    install(monkeypatch, FakeRepository(guide))
    found = price_guide_service.get_price_guide(None, guide.guide_id, admin)
    result = price_guide_service.present(found, admin)
    assert result.guide_id == guide.guide_id
    assert result.created_by == guide.created_by


def test_business_user_does_not_see_who_created_a_guide(monkeypatch, seller):
    guide = build_saved_guide()
    install(monkeypatch, FakeRepository(guide))
    found = price_guide_service.get_price_guide(None, guide.guide_id, seller)
    result = price_guide_service.present(found, seller)
    assert result.created_by is None


def test_missing_guide_gives_404(monkeypatch, admin):
    install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        price_guide_service.get_price_guide(None, uuid.uuid4(), admin)
    assert error.value.status_code == 404
    assert error.value.detail == "Price guide not found."


def test_unknown_role_is_refused_with_its_name(monkeypatch):
    guide = build_saved_guide()
    install(monkeypatch, FakeRepository(guide))
    stranger = SimpleNamespace(user_id=uuid.uuid4(), role="GUEST")
    with pytest.raises(HTTPException) as error:
        price_guide_service.get_price_guide(None, guide.guide_id, stranger)
    assert error.value.status_code == 403
    assert error.value.detail == "Access denied: a guest cannot view price guides."


def test_business_user_with_unapproved_business_is_refused(monkeypatch, seller):
    guide = build_saved_guide()
    install(monkeypatch, FakeRepository(guide, approval=ApprovalStatus.PENDING))
    with pytest.raises(HTTPException) as error:
        price_guide_service.get_price_guide(None, guide.guide_id, seller)
    assert error.value.status_code == 403
    assert "your business is not approved" in error.value.detail
    assert "view price guides" in error.value.detail


def test_business_user_without_a_business_is_refused(monkeypatch, seller):
    guide = build_saved_guide()
    install(monkeypatch, FakeRepository(guide, approval=None))
    with pytest.raises(HTTPException) as error:
        price_guide_service.get_price_guide(None, guide.guide_id, seller)
    assert error.value.status_code == 403


def test_list_passes_the_filters_and_hides_creator_from_business_users(monkeypatch, seller):
    guide = build_saved_guide()
    repository = install(monkeypatch, FakeRepository(guide))
    found = price_guide_service.list_price_guides(
        None, seller, stream=Stream.SAWDUST, material="pine", limit=10, offset=5
    )
    assert repository.search_filters["stream"] == Stream.SAWDUST
    assert repository.search_filters["material"] == "pine"
    assert repository.search_filters["limit"] == 10
    assert repository.search_filters["offset"] == 5
    assert len(found) == 1
    result = price_guide_service.present(found[0], seller)
    assert result.created_by is None


def test_list_is_refused_for_an_unapproved_business(monkeypatch, seller):
    install(monkeypatch, FakeRepository(approval=ApprovalStatus.PENDING))
    with pytest.raises(HTTPException) as error:
        price_guide_service.list_price_guides(None, seller)
    assert error.value.status_code == 403


def test_admin_can_create_a_guide_and_is_saved_as_creator(monkeypatch, admin):
    repository = install(monkeypatch, FakeRepository())
    price_guide_service.create_price_guide(None, new_guide_data(), admin)
    assert repository.created.created_by == admin.user_id
    assert repository.created.material == "Pine sawdust"


def test_business_user_cannot_create_a_guide(monkeypatch, seller):
    repository = install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        price_guide_service.create_price_guide(None, new_guide_data(), seller)
    assert error.value.status_code == 403
    assert "cannot create price guides" in error.value.detail
    assert repository.created is None


def test_create_checks_for_duplicates_using_stream_material_grade_and_district(monkeypatch, admin):
    repository = install(monkeypatch, FakeRepository())
    data = new_guide_data(grade="dry", district="Kigali")
    price_guide_service.create_price_guide(None, data, admin)
    assert repository.duplicate_filters["stream"] == Stream.SAWDUST
    assert repository.duplicate_filters["material"] == "Pine sawdust"
    assert repository.duplicate_filters["grade"] == "dry"
    assert repository.duplicate_filters["district"] == "Kigali"
    assert repository.duplicate_filters["exclude_id"] is None
    assert "unit" not in repository.duplicate_filters
    assert "source_date" not in repository.duplicate_filters


def test_creating_a_duplicate_gives_409(monkeypatch, admin):
    repository = install(monkeypatch, FakeRepository(duplicate=build_saved_guide()))
    with pytest.raises(HTTPException) as error:
        price_guide_service.create_price_guide(None, new_guide_data(), admin)
    assert error.value.status_code == 409
    assert "already exists" in error.value.detail
    assert repository.created is None


def test_create_with_an_invalid_user_gives_401(monkeypatch, admin):
    repository = install(monkeypatch, FakeRepository())
    repository.fail_on_create = True
    with pytest.raises(HTTPException) as error:
        price_guide_service.create_price_guide(None, new_guide_data(), admin)
    assert error.value.status_code == 401


def test_admin_can_update_a_guide(monkeypatch, admin):
    guide = build_saved_guide()
    install(monkeypatch, FakeRepository(guide))
    result = price_guide_service.update_price_guide(
        None, guide.guide_id, PriceGuideUpdate(max_price="80"), admin
    )
    assert result.max_price == Decimal("80")


def test_business_user_cannot_update_a_guide(monkeypatch, seller):
    guide = build_saved_guide()
    install(monkeypatch, FakeRepository(guide))
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(max_price="80"), seller
        )
    assert error.value.status_code == 403
    assert "cannot update price guides" in error.value.detail


def test_update_with_no_fields_gives_400(monkeypatch, admin):
    guide = build_saved_guide()
    install(monkeypatch, FakeRepository(guide))
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(None, guide.guide_id, PriceGuideUpdate(), admin)
    assert error.value.status_code == 400
    assert error.value.detail == "Nothing to update. Send at least one field."


def test_update_of_a_missing_guide_gives_404(monkeypatch, admin):
    install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, uuid.uuid4(), PriceGuideUpdate(max_price="80"), admin
        )
    assert error.value.status_code == 404


def test_update_with_max_below_the_saved_min_gives_422(monkeypatch, admin):
    guide = build_saved_guide()
    install(monkeypatch, FakeRepository(guide))
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(max_price="10"), admin
        )
    assert error.value.status_code == 422
    assert "Max price cannot be below min price" in error.value.detail


def test_update_with_a_grade_that_does_not_fit_the_stream_gives_422(monkeypatch, admin):
    guide = build_saved_guide(grade="dry")
    install(monkeypatch, FakeRepository(guide))
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(stream=Stream.GLASS), admin
        )
    assert error.value.status_code == 422
    assert "not valid for" in error.value.detail


def test_update_into_a_duplicate_gives_409_and_ignores_the_guide_itself(monkeypatch, admin):
    guide = build_saved_guide()
    repository = install(monkeypatch, FakeRepository(guide, duplicate=build_saved_guide()))
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(district="Kigali"), admin
        )
    assert error.value.status_code == 409
    assert repository.duplicate_filters["exclude_id"] == guide.guide_id
    assert repository.duplicate_filters["district"] == "Kigali"


def test_admin_can_delete_a_guide(monkeypatch, admin):
    guide = build_saved_guide()
    repository = install(monkeypatch, FakeRepository(guide))
    price_guide_service.delete_price_guide(None, guide.guide_id, admin)
    assert repository.deleted is guide


def test_business_user_cannot_delete_a_guide(monkeypatch, seller):
    guide = build_saved_guide()
    repository = install(monkeypatch, FakeRepository(guide))
    with pytest.raises(HTTPException) as error:
        price_guide_service.delete_price_guide(None, guide.guide_id, seller)
    assert error.value.status_code == 403
    assert repository.deleted is None


def test_delete_of_a_missing_guide_gives_404(monkeypatch, admin):
    install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        price_guide_service.delete_price_guide(None, uuid.uuid4(), admin)
    assert error.value.status_code == 404


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


def test_check_without_a_guide_has_no_guide_and_no_position(monkeypatch, admin):
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


def test_check_without_a_price_has_no_position(monkeypatch, admin):
    install(monkeypatch, FakeRepository(best=build_saved_guide()))
    result = price_guide_service.check_price(
        None, admin, stream=Stream.SAWDUST, material="Pine sawdust", unit=Unit.KILOGRAM
    )
    assert result.guide is not None
    assert result.position is None


def test_check_hides_creator_from_business_users(monkeypatch, seller):
    install(monkeypatch, FakeRepository(best=build_saved_guide()))
    result = price_guide_service.check_price(
        None, seller, stream=Stream.SAWDUST, material="Pine sawdust", unit=Unit.KILOGRAM
    )
    assert result.guide.created_by is None


def test_check_is_refused_for_an_unapproved_business(monkeypatch, seller):
    install(monkeypatch, FakeRepository(best=build_saved_guide(), approval=ApprovalStatus.REJECTED))
    with pytest.raises(HTTPException) as error:
        price_guide_service.check_price(
            None, seller, stream=Stream.SAWDUST, material="Pine sawdust", unit=Unit.KILOGRAM
        )
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "price, expected",
    [
        (Decimal("10"), "below"),
        (Decimal("30"), "within"),
        (Decimal("45"), "within"),
        (Decimal("60"), "within"),
        (Decimal("61"), "above"),
        (None, None),
    ],
)
def test_position_of_a_price(price, expected):
    assert _position_of(price, build_saved_guide()) == expected