from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from models.enums import Stream, Unit
from schemas.price_guides import PriceGuideCreate, PriceGuideUpdate


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


def test_max_price_below_min_price_is_rejected():
    with pytest.raises(ValidationError):
        PriceGuideCreate(**payload(min_price="60", max_price="30"))


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


def test_source_date_in_the_future_is_rejected():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValidationError):
        PriceGuideCreate(**payload(source_date=tomorrow))


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


def test_update_rejects_a_future_source_date():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValidationError):
        PriceGuideUpdate(source_date=tomorrow)


def test_update_rejects_a_blank_material():
    with pytest.raises(ValidationError):
        PriceGuideUpdate(material="  ")


def test_update_rejects_a_price_of_zero():
    with pytest.raises(ValidationError):
        PriceGuideUpdate(min_price="0")
