import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from models import PriceGuide
from models.enums import Stream, Unit
from schemas.price_guides import PriceGuideCreate, PriceGuideUpdate
from services.price_guides import (
    InvalidPriceRange,
    PriceGuideNotFound,
    PriceGuideService,
    UnknownUser,
    position_of,
)
from tests.price_guide_helpers import guide_values


def build_guide(**changes):
    return PriceGuide(guide_id=uuid.uuid4(), **guide_values(**changes))


class FakeRepository:
    def __init__(self, *guides, best=None, fail_add=False):
        self.guides = {guide.guide_id: guide for guide in guides}
        self.best = best
        self.fail_add = fail_add
        self.added = None
        self.searched = None

    def add(self, **values):
        if self.fail_add:
            raise IntegrityError("insert", {}, Exception("missing user"))
        self.added = values
        guide = PriceGuide(guide_id=uuid.uuid4(), **values)
        self.guides[guide.guide_id] = guide
        return guide

    def get(self, guide_id):
        return self.guides.get(guide_id)

    def search(self, **filters):
        self.searched = filters
        return list(self.guides.values())

    def find_best(self, **filters):
        return self.best

    def update(self, guide, changes):
        for name, value in changes.items():
            setattr(guide, name, value)
        return guide

    def delete(self, guide):
        del self.guides[guide.guide_id]


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


def test_create_saves_the_data_and_who_created_it():
    repository = FakeRepository()
    admin_id = uuid.uuid4()
    guide = PriceGuideService(repository).create(new_guide_data(), admin_id)
    assert repository.added["created_by"] == admin_id
    assert repository.added["material"] == "Pine sawdust"
    assert guide.min_price == Decimal("30")


def test_create_reports_an_unknown_user():
    service = PriceGuideService(FakeRepository(fail_add=True))
    with pytest.raises(UnknownUser):
        service.create(new_guide_data(), uuid.uuid4())


def test_get_returns_the_guide():
    guide = build_guide()
    assert PriceGuideService(FakeRepository(guide)).get(guide.guide_id) is guide


def test_get_unknown_guide_is_not_found():
    with pytest.raises(PriceGuideNotFound):
        PriceGuideService(FakeRepository()).get(uuid.uuid4())


def test_list_passes_the_filters_on():
    repository = FakeRepository(build_guide())
    PriceGuideService(repository).list(stream=Stream.SAWDUST, limit=5, offset=10)
    assert repository.searched == {"stream": Stream.SAWDUST, "limit": 5, "offset": 10}


def test_update_changes_only_the_given_fields():
    guide = build_guide()
    service = PriceGuideService(FakeRepository(guide))
    service.update(guide.guide_id, PriceGuideUpdate(max_price="80"))
    assert guide.max_price == Decimal("80")
    assert guide.min_price == Decimal("30")
    assert guide.material == "Pine sawdust"


def test_update_cannot_put_max_price_below_the_saved_min_price():
    guide = build_guide()
    service = PriceGuideService(FakeRepository(guide))
    with pytest.raises(InvalidPriceRange):
        service.update(guide.guide_id, PriceGuideUpdate(max_price="10"))


def test_update_cannot_put_min_price_above_the_saved_max_price():
    guide = build_guide()
    service = PriceGuideService(FakeRepository(guide))
    with pytest.raises(InvalidPriceRange):
        service.update(guide.guide_id, PriceGuideUpdate(min_price="100"))


def test_update_can_move_both_prices_together():
    guide = build_guide()
    service = PriceGuideService(FakeRepository(guide))
    service.update(guide.guide_id, PriceGuideUpdate(min_price="100", max_price="120"))
    assert (guide.min_price, guide.max_price) == (Decimal("100"), Decimal("120"))


def test_update_can_clear_the_district():
    guide = build_guide(district="Gasabo")
    service = PriceGuideService(FakeRepository(guide))
    service.update(guide.guide_id, PriceGuideUpdate(district=None))
    assert guide.district is None


def test_update_ignores_a_null_material():
    guide = build_guide()
    service = PriceGuideService(FakeRepository(guide))
    service.update(guide.guide_id, PriceGuideUpdate(material=None))
    assert guide.material == "Pine sawdust"


def test_update_unknown_guide_is_not_found():
    with pytest.raises(PriceGuideNotFound):
        PriceGuideService(FakeRepository()).update(
            uuid.uuid4(), PriceGuideUpdate(max_price="80")
        )


def test_delete_removes_the_guide():
    guide = build_guide()
    repository = FakeRepository(guide)
    PriceGuideService(repository).delete(guide.guide_id)
    assert repository.guides == {}


def test_delete_unknown_guide_is_not_found():
    with pytest.raises(PriceGuideNotFound):
        PriceGuideService(FakeRepository()).delete(uuid.uuid4())


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


def test_check_returns_the_guide_and_where_the_price_sits():
    guide = build_guide()
    service = PriceGuideService(FakeRepository(best=guide))
    result = service.check(
        stream=Stream.SAWDUST,
        material="pine sawdust",
        unit=Unit.KILOGRAM,
        price=Decimal("90"),
    )
    assert result == (guide, "above")


def test_check_without_a_guide_has_no_position():
    service = PriceGuideService(FakeRepository())
    result = service.check(
        stream=Stream.GLASS,
        material="Cullet",
        unit=Unit.TONNE,
        price=Decimal("90"),
    )
    assert result == (None, None)


def test_service_works_with_any_repository_object():
    repository = SimpleNamespace(find_best=lambda **_: None)
    result = PriceGuideService(repository).check(
        stream=Stream.GLASS, material="Cullet", unit=Unit.TONNE
    )
    assert result == (None, None)
