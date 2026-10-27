import uuid
from datetime import date
from decimal import Decimal

from models.listing import Stream, Unit
from repositories.price_guide import price_guide_repository
from tests.price_guide_helpers import guide_values, make_guide


def find_best(session, **filters):
    values = dict(
        stream=Stream.SAWDUST, material="Pine sawdust", unit=Unit.KILOGRAM
    )
    values.update(filters)
    return price_guide_repository.find_best(session, **values)


def test_create_saves_a_guide_that_can_be_found_again(session):
    guide = price_guide_repository.create(session, guide_values())
    assert price_guide_repository.get(session, guide.guide_id).material == "Pine sawdust"


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
        unit=Unit.KILOGRAM,
        district=None,
        source_date=guide.source_date,
    )
    assert found.guide_id == guide.guide_id


def test_find_duplicate_ignores_a_different_grade_or_district(session):
    guide = make_guide(session, grade="dry", district=None)
    same = dict(
        stream=Stream.SAWDUST,
        material="Pine sawdust",
        unit=Unit.KILOGRAM,
        source_date=guide.source_date,
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
        unit=Unit.KILOGRAM,
        district=None,
        source_date=guide.source_date,
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