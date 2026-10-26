import uuid
from datetime import date
from decimal import Decimal

from models.enums import Stream, Unit
from repositories.price_guides import PriceGuideRepository
from tests.price_guide_helpers import guide_values, make_guide


def test_add_saves_a_guide_that_can_be_found_again(session):
    repository = PriceGuideRepository(session)
    guide = repository.add(**guide_values())
    assert repository.get(guide.guide_id).material == "Pine sawdust"


def test_get_returns_nothing_for_an_unknown_id(session):
    assert PriceGuideRepository(session).get(uuid.uuid4()) is None


def test_search_filters_by_stream_and_unit(session):
    make_guide(session)
    make_guide(session, stream=Stream.GLASS, material="Cullet", unit=Unit.TONNE)
    repository = PriceGuideRepository(session)
    found = repository.search(stream=Stream.GLASS)
    assert [guide.material for guide in found] == ["Cullet"]
    assert repository.search(unit=Unit.PIECE) == []


def test_search_finds_part_of_a_material_name_in_any_case(session):
    make_guide(session, material="Pine sawdust")
    make_guide(session, material="Plastic flakes", stream=Stream.PLASTIC)
    found = PriceGuideRepository(session).search(material="SAWD")
    assert [guide.material for guide in found] == ["Pine sawdust"]


def test_search_treats_percent_as_a_normal_character(session):
    make_guide(session)
    assert PriceGuideRepository(session).search(material="%") == []


def test_search_filters_by_district_in_any_case(session):
    make_guide(session, district="Gasabo")
    make_guide(session, district="Kicukiro", material="Oak sawdust")
    found = PriceGuideRepository(session).search(district="gasabo")
    assert [guide.district for guide in found] == ["Gasabo"]


def test_search_shows_the_newest_source_first(session):
    make_guide(session, material="Old", source_date=date(2025, 1, 1))
    make_guide(session, material="New", source_date=date(2026, 6, 1))
    found = PriceGuideRepository(session).search()
    assert [guide.material for guide in found] == ["New", "Old"]


def test_search_pages_with_limit_and_offset(session):
    for number in range(3):
        make_guide(session, material=f"Item {number}", source_date=date(2026, 1, 1))
    repository = PriceGuideRepository(session)
    assert len(repository.search(limit=2)) == 2
    assert len(repository.search(limit=2, offset=2)) == 1


def test_find_best_ignores_the_case_of_the_material(session):
    guide = make_guide(session)
    found = PriceGuideRepository(session).find_best(
        stream=Stream.SAWDUST, material="PINE SAWDUST", unit=Unit.KILOGRAM
    )
    assert found.guide_id == guide.guide_id


def test_find_best_needs_the_same_stream_and_unit(session):
    make_guide(session)
    repository = PriceGuideRepository(session)
    assert (
        repository.find_best(
            stream=Stream.GLASS, material="Pine sawdust", unit=Unit.KILOGRAM
        )
        is None
    )
    assert (
        repository.find_best(
            stream=Stream.SAWDUST, material="Pine sawdust", unit=Unit.TONNE
        )
        is None
    )


def test_find_best_takes_the_newest_guide(session):
    make_guide(session, source_date=date(2025, 1, 1), max_price=Decimal("55"))
    newest = make_guide(session, source_date=date(2026, 5, 1))
    found = PriceGuideRepository(session).find_best(
        stream=Stream.SAWDUST, material="Pine sawdust", unit=Unit.KILOGRAM
    )
    assert found.guide_id == newest.guide_id


def test_find_best_prefers_the_matching_district(session):
    make_guide(session, source_date=date(2026, 6, 1))
    local = make_guide(session, district="Gasabo", source_date=date(2025, 1, 1))
    found = PriceGuideRepository(session).find_best(
        stream=Stream.SAWDUST,
        material="Pine sawdust",
        unit=Unit.KILOGRAM,
        district="Gasabo",
    )
    assert found.guide_id == local.guide_id


def test_find_best_falls_back_to_the_guide_for_all_districts(session):
    general = make_guide(session)
    make_guide(session, district="Kicukiro", source_date=date(2026, 6, 1))
    found = PriceGuideRepository(session).find_best(
        stream=Stream.SAWDUST,
        material="Pine sawdust",
        unit=Unit.KILOGRAM,
        district="Gasabo",
    )
    assert found.guide_id == general.guide_id


def test_find_best_skips_other_districts_when_there_is_no_general_guide(session):
    make_guide(session, district="Kicukiro")
    found = PriceGuideRepository(session).find_best(
        stream=Stream.SAWDUST,
        material="Pine sawdust",
        unit=Unit.KILOGRAM,
        district="Gasabo",
    )
    assert found is None


def test_update_saves_the_changes(session):
    guide = make_guide(session)
    updated = PriceGuideRepository(session).update(
        guide, {"max_price": Decimal("90"), "district": "Gasabo"}
    )
    assert updated.max_price == Decimal("90")
    assert updated.district == "Gasabo"


def test_delete_removes_the_guide(session):
    guide = make_guide(session)
    repository = PriceGuideRepository(session)
    repository.delete(guide)
    assert repository.get(guide.guide_id) is None
