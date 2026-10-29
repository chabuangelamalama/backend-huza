import uuid
import pytest
import services.price_guide as service_module
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from models import User
from models.business import ApprovalStatus
from models.listing import Stream, Unit
from models.user import UserRole
from tests.test_models import make_business, make_location
from pydantic import ValidationError
from schemas.price_guide import PriceGuideCreate, PriceGuideUpdate
from sqlalchemy.exc import IntegrityError
from repositories.price_guide import price_guide_repository
from types import SimpleNamespace
from fastapi import HTTPException
from models.price_guide import PriceGuide, GRADES_BY_STREAM
from services.price_guide import _position_of, price_guide_service
from fastapi.testclient import TestClient
from database import get_db
from core.security import create_access_token
from main import app


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


def payload(**changes):
    values = dict(
        stream="SAWDUST",
        material="Pine sawdust",
        unit="KILOGRAM",
        min_price="30",
        max_price="60",
        source="Kigali market survey",
        source_date=date.today().isoformat(),
    )
    values.update(changes)
    return values


def test_valid_guide_is_accepted():
    guide = PriceGuideCreate(**payload())
    assert guide.stream == Stream.SAWDUST
    assert guide.unit == Unit.KILOGRAM
    assert guide.min_price == Decimal("30")
    assert guide.grade is None


def test_same_min_and_max_price_is_accepted():
    guide = PriceGuideCreate(**payload(min_price="50", max_price="50"))
    assert guide.min_price == guide.max_price


@pytest.mark.parametrize("price", ["0", "-5"])
def test_min_price_must_be_above_zero(price):
    with pytest.raises(ValidationError):
        PriceGuideCreate(**payload(min_price=price))


def test_prices_allow_at_most_four_decimal_places():
    with pytest.raises(ValidationError):
        PriceGuideCreate(**payload(min_price="1.23456", max_price="5"))


def test_blank_material_is_rejected():
    with pytest.raises(ValidationError):
        PriceGuideCreate(**payload(material="   "))


def test_text_is_trimmed():
    guide = PriceGuideCreate(
        **payload(material="  Pine sawdust  ", district="  Gasabo ")
    )
    assert guide.material == "Pine sawdust"
    assert guide.district == "Gasabo"


def test_unknown_stream_is_rejected():
    with pytest.raises(ValidationError):
        PriceGuideCreate(**payload(stream="GOLD"))


def test_unknown_unit_is_rejected():
    with pytest.raises(ValidationError):
        PriceGuideCreate(**payload(unit="LITRE"))


def test_sample_size_must_be_positive():
    with pytest.raises(ValidationError):
        PriceGuideCreate(**payload(sample_size=0))


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        PriceGuideCreate(**payload(created_by="3f2b1c1e-0000-0000-0000-000000000000"))


def test_update_accepts_a_single_field():
    update = PriceGuideUpdate(max_price="80")
    assert update.model_dump(exclude_unset=True) == {"max_price": Decimal("80")}


def test_update_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        PriceGuideUpdate(guide_id="x")


def test_update_rejects_a_blank_material():
    with pytest.raises(ValidationError):
        PriceGuideUpdate(material="  ")


def test_update_rejects_a_price_of_zero():
    with pytest.raises(ValidationError):
        PriceGuideUpdate(min_price="0")


def test_a_new_guide_gets_an_id_and_dates(session):
    guide = make_guide(session)
    assert guide.guide_id is not None
    assert guide.created_at is not None
    assert guide.updated_at is not None
    assert guide.grade is None
    assert guide.created_by is None


def test_min_price_must_be_above_zero_models(session):
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


def find_best(session, **filters):
    values = dict(stream=Stream.SAWDUST, material="Pine sawdust", unit=Unit.KILOGRAM)
    values.update(filters)
    return price_guide_repository.find_best(session, **values)


def test_create_saves_a_guide_that_can_be_found_again(session):
    guide = price_guide_repository.create(session, guide_values())
    assert (
        price_guide_repository.get(session, guide.guide_id).material == "Pine sawdust"
    )


def test_get_returns_nothing_for_an_unknown_id(session):
    assert price_guide_repository.get(session, uuid.uuid4()) is None


def test_search_filters_by_stream_and_unit(session):
    make_guide(session)
    make_guide(session, stream=Stream.GLASS, material="Cullet", unit=Unit.TONNE)
    found = price_guide_repository.search(session, stream=Stream.GLASS)
    assert [guide.material for guide in found] == ["Cullet"]
    assert price_guide_repository.search(session, unit=Unit.PIECE) == []


def test_search_finds_part_of_a_material_name_in_any_case(session):
    make_guide(session, material="Pine sawdust")
    make_guide(session, material="Plastic flakes", stream=Stream.PLASTIC)
    found = price_guide_repository.search(session, material="SAWD")
    assert [guide.material for guide in found] == ["Pine sawdust"]


def test_search_treats_percent_as_a_normal_character(session):
    make_guide(session)
    assert price_guide_repository.search(session, material="%") == []


def test_search_filters_by_district_in_any_case(session):
    make_guide(session, district="Gasabo")
    make_guide(session, district="Kicukiro", material="Oak sawdust")
    found = price_guide_repository.search(session, district="gasabo")
    assert [guide.district for guide in found] == ["Gasabo"]


def test_search_filters_by_grade_in_any_case(session):
    make_guide(session, grade="dry")
    make_guide(session, grade="wet", material="Oak sawdust")
    found = price_guide_repository.search(session, grade="WET")
    assert [guide.material for guide in found] == ["Oak sawdust"]


def test_search_shows_the_newest_source_first(session):
    make_guide(session, material="Old", source_date=date(2025, 1, 1))
    make_guide(session, material="New", source_date=date(2026, 6, 1))
    found = price_guide_repository.search(session)
    assert [guide.material for guide in found] == ["New", "Old"]


def test_search_pages_with_limit_and_offset(session):
    for number in range(3):
        make_guide(session, material=f"Item {number}", source_date=date(2026, 1, 1))
    assert len(price_guide_repository.search(session, limit=2)) == 2
    assert len(price_guide_repository.search(session, limit=2, offset=2)) == 1


def test_find_best_ignores_the_case_of_the_material(session):
    guide = make_guide(session)
    found = find_best(session, material="PINE SAWDUST")
    assert found.guide_id == guide.guide_id


def test_find_best_needs_the_same_stream_and_unit(session):
    make_guide(session)
    assert find_best(session, stream=Stream.GLASS) is None
    assert find_best(session, unit=Unit.TONNE) is None


def test_find_best_takes_the_newest_guide(session):
    make_guide(session, source_date=date(2025, 1, 1), max_price=Decimal("55"))
    newest = make_guide(session, source_date=date(2026, 5, 1))
    found = find_best(session)
    assert found.guide_id == newest.guide_id


def test_find_best_prefers_the_matching_district(session):
    make_guide(session, source_date=date(2026, 6, 1))
    local = make_guide(session, district="Gasabo", source_date=date(2025, 1, 1))
    found = find_best(session, district="Gasabo")
    assert found.guide_id == local.guide_id


def test_find_best_falls_back_to_the_guide_for_all_districts(session):
    general = make_guide(session)
    make_guide(session, district="Kicukiro", source_date=date(2026, 6, 1))
    found = find_best(session, district="Gasabo")
    assert found.guide_id == general.guide_id


def test_find_best_skips_other_districts_when_there_is_no_general_guide(session):
    make_guide(session, district="Kicukiro")
    assert find_best(session, district="Gasabo") is None


def test_find_best_prefers_the_matching_grade(session):
    make_guide(session, grade="wet", source_date=date(2026, 6, 1))
    dry = make_guide(session, grade="dry", source_date=date(2025, 1, 1))
    found = find_best(session, grade="dry")
    assert found.guide_id == dry.guide_id


def test_find_best_falls_back_to_a_guide_without_a_grade(session):
    general = make_guide(session, grade=None)
    make_guide(session, grade="wet", source_date=date(2026, 6, 1))
    found = find_best(session, grade="dry")
    assert found.guide_id == general.guide_id


def test_find_best_skips_other_grades_when_there_is_no_general_guide(session):
    make_guide(session, grade="wet")
    assert find_best(session, grade="dry") is None


def test_find_duplicate_finds_the_same_guide_in_any_case(session):
    guide = make_guide(session, grade="dry", district=None)
    found = price_guide_repository.find_duplicate(
        session,
        stream=Stream.SAWDUST,
        material="PINE SAWDUST",
        grade="dry",
        district=None,
    )
    assert found.guide_id == guide.guide_id


def test_find_duplicate_ignores_a_different_grade_or_district(session):
    make_guide(session, grade="dry", district=None)
    same = dict(
        stream=Stream.SAWDUST,
        material="Pine sawdust",
    )
    other_grade = price_guide_repository.find_duplicate(
        session, grade="wet", district=None, **same
    )
    other_district = price_guide_repository.find_duplicate(
        session, grade="dry", district="Gasabo", **same
    )
    assert other_grade is None
    assert other_district is None


def test_find_duplicate_can_skip_the_guide_being_updated(session):
    guide = make_guide(session, grade="dry", district=None)
    found = price_guide_repository.find_duplicate(
        session,
        stream=Stream.SAWDUST,
        material="Pine sawdust",
        grade="dry",
        district=None,
        exclude_id=guide.guide_id,
    )
    assert found is None


def test_update_saves_the_changes(session):
    guide = make_guide(session)
    updated = price_guide_repository.update(
        session, guide, {"max_price": Decimal("90"), "district": "Gasabo"}
    )
    assert updated.max_price == Decimal("90")
    assert updated.district == "Gasabo"


def test_delete_removes_the_guide(session):
    guide = make_guide(session)
    price_guide_repository.delete(session, guide)
    assert price_guide_repository.get(session, guide.guide_id) is None


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
    def __init__(
        self, guide=None, duplicate=None, best=None, approval=ApprovalStatus.APPROVED
    ):
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


def test_list_passes_the_filters_and_hides_creator_from_business_users(
    monkeypatch, seller
):
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


def test_create_checks_for_duplicates_using_stream_material_grade_and_district(
    monkeypatch, admin
):
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
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(), admin
        )
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


def test_update_into_a_duplicate_gives_409_and_ignores_the_guide_itself(
    monkeypatch, admin
):
    guide = build_saved_guide()
    repository = install(
        monkeypatch, FakeRepository(guide, duplicate=build_saved_guide())
    )
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
    install(
        monkeypatch,
        FakeRepository(best=build_saved_guide(), approval=ApprovalStatus.REJECTED),
    )
    with pytest.raises(HTTPException) as error:
        price_guide_service.check_price(
            None,
            seller,
            stream=Stream.SAWDUST,
            material="Pine sawdust",
            unit=Unit.KILOGRAM,
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


class FakeRepositoryRules:
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
def repository(monkeypatch):
    repository = FakeRepositoryRules(saved_guide())
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


class FakeRepositoryGrades:
    def __init__(self, guide=None, duplicate=None):
        self.guide = guide
        self.duplicate = duplicate

    def get(self, db, guide_id):
        return self.guide

    def find_duplicate(self, db, **kwargs):
        return self.duplicate

    def create(self, db, data):
        return data

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
        service_module, "price_guide_repository", FakeRepositoryGrades(guide, duplicate)
    )
    return guide


def use_empty_repository(monkeypatch):
    monkeypatch.setattr(
        service_module, "price_guide_repository", FakeRepositoryGrades()
    )


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
def test_create_accepts_valid_grade(monkeypatch, admin, stream, grade):
    use_empty_repository(monkeypatch)
    data = PriceGuideCreate(**make_payload(stream, grade))
    saved = price_guide_service.create_price_guide(None, data, admin)
    assert saved["grade"] == grade


def test_create_accepts_missing_grade(monkeypatch, admin):
    use_empty_repository(monkeypatch)
    data = PriceGuideCreate(**make_payload(Stream.GLASS, None))
    saved = price_guide_service.create_price_guide(None, data, admin)
    assert saved["grade"] is None


def test_create_lowercases_grade(monkeypatch, admin):
    use_empty_repository(monkeypatch)
    data = PriceGuideCreate(**make_payload(Stream.GLASS, "Clear"))
    saved = price_guide_service.create_price_guide(None, data, admin)
    assert saved["grade"] == "clear"


@pytest.mark.parametrize(
    "stream, grade",
    [
        (Stream.SAWDUST, "green"),
        (Stream.PLASTIC, "clear"),
        (Stream.GARMENT_OFFCUTS, "dry"),
        (Stream.GLASS, "A"),
    ],
)
def test_create_rejects_grade_from_another_stream(monkeypatch, admin, stream, grade):
    use_empty_repository(monkeypatch)
    data = PriceGuideCreate(**make_payload(stream, grade))
    with pytest.raises(HTTPException) as error:
        price_guide_service.create_price_guide(None, data, admin)
    assert error.value.status_code == 422
    assert "Allowed grades" in error.value.detail


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


def test_service_lowercases_grade_on_update(monkeypatch, admin):
    guide = use_guide(monkeypatch, Stream.GLASS, "clear")
    changes = price_guide_service.update_price_guide(
        None, guide.guide_id, PriceGuideUpdate(grade="AMBER"), admin
    )
    assert changes == {"grade": "amber"}


def test_service_rejects_empty_update(monkeypatch, admin):
    guide = use_guide(monkeypatch, Stream.GLASS, "clear")
    with pytest.raises(HTTPException) as error:
        price_guide_service.update_price_guide(
            None, guide.guide_id, PriceGuideUpdate(), admin
        )
    assert error.value.status_code == 400


def test_service_rejects_update_that_makes_a_duplicate(monkeypatch, admin):
    guide = use_guide(monkeypatch, Stream.GLASS, "clear", duplicate=SimpleNamespace())
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


URL = "/price-guides"


LOOKUP = "/price-guides/lookup"


def headers_for(user):
    token = create_access_token(user.user_id, user.user_role)
    return {"Authorization": f"Bearer {token}"}


def new_guide_body(**changes):
    body = dict(
        stream="SAWDUST",
        material="Pine sawdust",
        unit="KILOGRAM",
        min_price=30,
        max_price=60,
        source="Kigali market survey",
        source_date=date.today().isoformat(),
    )
    body.update(changes)
    return body


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_api(session):
    return make_admin(session)


@pytest.fixture
def seller_api(session):
    return make_business_user(session)


@pytest.fixture
def unapproved_seller(session):
    return make_business_user(session, email="pending@example.rw", approval=None)


def test_listing_needs_a_login(client):
    assert client.get(URL).status_code == 401


def test_a_bad_token_is_rejected(client):
    response = client.get(URL, headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


def test_an_expired_token_is_rejected(client, admin_api):
    token = create_access_token(admin_api.user_id, UserRole.ADMIN, expires_minutes=-5)
    response = client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_a_business_user_can_read_the_guides(client, seller_api, session):
    make_guide(session)
    response = client.get(URL, headers=headers_for(seller_api))
    assert response.status_code == 200
    assert [guide["material"] for guide in response.json()] == ["Pine sawdust"]


def test_a_business_user_that_is_not_approved_cannot_read_the_guides(
    client, unapproved_seller, session
):
    make_guide(session)
    response = client.get(URL, headers=headers_for(unapproved_seller))
    assert response.status_code == 403
    assert "your business is not approved" in response.json()["detail"]


def test_a_business_user_that_is_not_approved_cannot_use_the_lookup(
    client, unapproved_seller, session
):
    make_guide(session)
    response = client.get(
        LOOKUP,
        params={"stream": "SAWDUST", "material": "Pine sawdust", "unit": "KILOGRAM"},
        headers=headers_for(unapproved_seller),
    )
    assert response.status_code == 403


def test_a_business_user_cannot_create_a_guide(client, seller_api):
    response = client.post(URL, json=new_guide_body(), headers=headers_for(seller_api))
    assert response.status_code == 403
    assert "cannot create price guides" in response.json()["detail"]


def test_an_admin_can_create_a_guide(client, admin_api):
    response = client.post(URL, json=new_guide_body(), headers=headers_for(admin_api))
    assert response.status_code == 200
    body = response.json()
    assert body["material"] == "Pine sawdust"
    assert Decimal(body["min_price"]) == Decimal("30")
    assert body["guide_id"]


def test_an_admin_sees_who_created_a_guide(client, admin_api):
    response = client.post(URL, json=new_guide_body(), headers=headers_for(admin_api))
    assert response.json()["created_by"] == str(admin_api.user_id)


def test_a_business_user_does_not_see_who_created_a_guide(
    client, admin_api, seller_api, session
):
    guide = make_guide(session, created_by=admin_api.user_id)
    one = client.get(f"{URL}/{guide.guide_id}", headers=headers_for(seller_api))
    assert one.status_code == 200
    assert one.json()["created_by"] is None
    many = client.get(URL, headers=headers_for(seller_api))
    assert many.json()[0]["created_by"] is None


def test_creating_with_max_price_below_min_price_fails(client, admin_api):
    body = new_guide_body(min_price=60, max_price=30)
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 422


def test_creating_with_a_future_date_fails(client, admin_api):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    body = new_guide_body(source_date=tomorrow)
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 422


def test_creating_with_a_missing_field_fails(client, admin_api):
    body = new_guide_body()
    del body["source"]
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 422


def test_creating_with_an_unknown_field_fails(client, admin_api):
    body = new_guide_body(colour="red")
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 422


def test_a_token_for_a_user_that_does_not_exist_cannot_create(client):
    token = create_access_token(uuid.uuid4(), UserRole.ADMIN)
    response = client.post(
        URL, json=new_guide_body(), headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_creating_with_a_valid_grade_saves_it_in_lowercase(client, admin_api):
    body = new_guide_body(grade="Dry")
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 200
    assert response.json()["grade"] == "dry"


def test_creating_with_a_grade_from_another_stream_fails(client, admin_api):
    body = new_guide_body(grade="hard")
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 422


def test_creating_a_glass_guide_with_a_glass_grade_works(client, admin_api):
    body = new_guide_body(
        stream="GLASS", material="Cullet", unit="TONNE", grade="clear"
    )
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 200
    assert response.json()["grade"] == "clear"


def test_creating_the_same_guide_twice_gives_409(client, admin_api):
    first = client.post(URL, json=new_guide_body(), headers=headers_for(admin_api))
    assert first.status_code == 200
    second = client.post(URL, json=new_guide_body(), headers=headers_for(admin_api))
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]


def test_the_same_material_in_other_letters_is_still_a_duplicate(client, admin_api):
    client.post(URL, json=new_guide_body(), headers=headers_for(admin_api))
    response = client.post(
        URL,
        json=new_guide_body(material="PINE SAWDUST"),
        headers=headers_for(admin_api),
    )
    assert response.status_code == 409


def test_the_same_material_with_another_grade_is_allowed(client, admin_api):
    client.post(URL, json=new_guide_body(grade="dry"), headers=headers_for(admin_api))
    response = client.post(
        URL, json=new_guide_body(grade="wet"), headers=headers_for(admin_api)
    )
    assert response.status_code == 200


def test_the_same_material_in_another_district_is_allowed(client, admin_api):
    client.post(
        URL, json=new_guide_body(district="Kigali"), headers=headers_for(admin_api)
    )
    response = client.post(
        URL, json=new_guide_body(district="Huye"), headers=headers_for(admin_api)
    )
    assert response.status_code == 200


def test_the_same_district_in_other_letters_is_a_duplicate(client, admin_api):
    client.post(
        URL, json=new_guide_body(district="Kigali"), headers=headers_for(admin_api)
    )
    response = client.post(
        URL, json=new_guide_body(district="KIGALI"), headers=headers_for(admin_api)
    )
    assert response.status_code == 409


def test_a_different_price_or_date_does_not_make_a_guide_new(client, admin_api):
    client.post(URL, json=new_guide_body(), headers=headers_for(admin_api))
    other_day = (date.today() - timedelta(days=30)).isoformat()
    response = client.post(
        URL,
        json=new_guide_body(min_price=10, max_price=20, source_date=other_day),
        headers=headers_for(admin_api),
    )
    assert response.status_code == 409


def test_the_list_can_be_filtered(client, admin_api, session):
    make_guide(session)
    make_guide(session, stream=Stream.GLASS, material="Cullet", unit=Unit.TONNE)
    response = client.get(
        URL,
        params={"stream": "GLASS", "material": "cul"},
        headers=headers_for(admin_api),
    )
    assert [guide["material"] for guide in response.json()] == ["Cullet"]


@pytest.mark.parametrize("limit", [0, 101])
def test_the_list_limit_must_be_between_1_and_100(client, admin_api, limit):
    response = client.get(URL, params={"limit": limit}, headers=headers_for(admin_api))
    assert response.status_code == 422


def test_one_guide_can_be_read(client, admin_api, session):
    guide = make_guide(session)
    response = client.get(f"{URL}/{guide.guide_id}", headers=headers_for(admin_api))
    assert response.status_code == 200
    assert response.json()["guide_id"] == str(guide.guide_id)


def test_reading_an_unknown_guide_gives_404(client, admin_api):
    response = client.get(f"{URL}/{uuid.uuid4()}", headers=headers_for(admin_api))
    assert response.status_code == 404
    assert response.json()["detail"] == "Price guide not found."


def test_reading_a_malformed_id_gives_422(client, admin_api):
    response = client.get(f"{URL}/not-an-id", headers=headers_for(admin_api))
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("price", "position"),
    [(20, "below"), (30, "within"), (45, "within"), (90, "above")],
)
def test_lookup_says_where_a_price_sits(client, seller_api, session, price, position):
    make_guide(session)
    response = client.get(
        LOOKUP,
        params={
            "stream": "SAWDUST",
            "material": "pine sawdust",
            "unit": "KILOGRAM",
            "price": price,
        },
        headers=headers_for(seller_api),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["position"] == position
    assert body["guide"]["material"] == "Pine sawdust"


def test_lookup_without_a_price_still_returns_the_guide(client, seller_api, session):
    make_guide(session)
    response = client.get(
        LOOKUP,
        params={"stream": "SAWDUST", "material": "Pine sawdust", "unit": "KILOGRAM"},
        headers=headers_for(seller_api),
    )
    body = response.json()
    assert body["position"] is None
    assert body["guide"] is not None


def test_lookup_prefers_the_guide_with_the_matching_grade(client, seller_api, session):
    make_guide(session, grade="dry", min_price=Decimal("30"), max_price=Decimal("60"))
    make_guide(session, grade="wet", min_price=Decimal("10"), max_price=Decimal("20"))
    response = client.get(
        LOOKUP,
        params={
            "stream": "SAWDUST",
            "material": "Pine sawdust",
            "unit": "KILOGRAM",
            "grade": "wet",
            "price": 15,
        },
        headers=headers_for(seller_api),
    )
    body = response.json()
    assert body["guide"]["grade"] == "wet"
    assert body["position"] == "within"


def test_lookup_with_no_matching_guide_returns_nothing(client, seller_api):
    response = client.get(
        LOOKUP,
        params={"stream": "GLASS", "material": "Cullet", "unit": "TONNE", "price": 5},
        headers=headers_for(seller_api),
    )
    assert response.status_code == 200
    assert response.json() == {"guide": None, "position": None}


def test_lookup_hides_the_creator_from_a_business_user(
    client, admin_api, seller_api, session
):
    make_guide(session, created_by=admin_api.user_id)
    response = client.get(
        LOOKUP,
        params={"stream": "SAWDUST", "material": "Pine sawdust", "unit": "KILOGRAM"},
        headers=headers_for(seller_api),
    )
    assert response.json()["guide"]["created_by"] is None


def test_lookup_price_must_be_above_zero(client, seller_api):
    response = client.get(
        LOOKUP,
        params={
            "stream": "SAWDUST",
            "material": "Pine sawdust",
            "unit": "KILOGRAM",
            "price": 0,
        },
        headers=headers_for(seller_api),
    )
    assert response.status_code == 422


def test_lookup_needs_a_login(client):
    response = client.get(
        LOOKUP,
        params={"stream": "SAWDUST", "material": "Pine sawdust", "unit": "KILOGRAM"},
    )
    assert response.status_code == 401


def test_an_admin_can_update_a_guide(client, admin_api, session):
    guide = make_guide(session)
    response = client.patch(
        f"{URL}/{guide.guide_id}",
        json={"max_price": 80},
        headers=headers_for(admin_api),
    )
    assert response.status_code == 200
    assert Decimal(response.json()["max_price"]) == Decimal("80")


def test_updating_with_max_price_below_min_price_fails(client, admin_api, session):
    guide = make_guide(session)
    response = client.patch(
        f"{URL}/{guide.guide_id}",
        json={"max_price": 10},
        headers=headers_for(admin_api),
    )
    assert response.status_code == 422


def test_updating_with_nothing_gives_400(client, admin_api, session):
    guide = make_guide(session)
    response = client.patch(
        f"{URL}/{guide.guide_id}", json={}, headers=headers_for(admin_api)
    )
    assert response.status_code == 400


def test_updating_to_a_grade_from_another_stream_fails(client, admin_api, session):
    guide = make_guide(session, grade="dry")
    response = client.patch(
        f"{URL}/{guide.guide_id}",
        json={"stream": "GLASS"},
        headers=headers_for(admin_api),
    )
    assert response.status_code == 422


def test_updating_into_a_duplicate_gives_409(client, admin_api, session):
    make_guide(session)
    other = make_guide(session, material="Oak sawdust")
    response = client.patch(
        f"{URL}/{other.guide_id}",
        json={"material": "Pine sawdust"},
        headers=headers_for(admin_api),
    )
    assert response.status_code == 409


def test_a_guide_can_be_updated_without_clashing_with_itself(
    client, admin_api, session
):
    guide = make_guide(session)
    response = client.patch(
        f"{URL}/{guide.guide_id}",
        json={"material": "Pine sawdust", "min_price": 25},
        headers=headers_for(admin_api),
    )
    assert response.status_code == 200


def test_a_business_user_cannot_update_a_guide(client, seller_api, session):
    guide = make_guide(session)
    response = client.patch(
        f"{URL}/{guide.guide_id}",
        json={"max_price": 80},
        headers=headers_for(seller_api),
    )
    assert response.status_code == 403


def test_updating_an_unknown_guide_gives_404(client, admin_api):
    response = client.patch(
        f"{URL}/{uuid.uuid4()}", json={"max_price": 80}, headers=headers_for(admin_api)
    )
    assert response.status_code == 404


def test_an_admin_can_delete_a_guide(client, admin_api, session):
    guide = make_guide(session)
    response = client.delete(f"{URL}/{guide.guide_id}", headers=headers_for(admin_api))
    assert response.status_code == 200
    again = client.get(f"{URL}/{guide.guide_id}", headers=headers_for(admin_api))
    assert again.status_code == 404


def test_a_business_user_cannot_delete_a_guide(client, seller_api, session):
    guide = make_guide(session)
    response = client.delete(f"{URL}/{guide.guide_id}", headers=headers_for(seller_api))
    assert response.status_code == 403


def test_deleting_an_unknown_guide_gives_404(client, admin_api):
    response = client.delete(f"{URL}/{uuid.uuid4()}", headers=headers_for(admin_api))
    assert response.status_code == 404
