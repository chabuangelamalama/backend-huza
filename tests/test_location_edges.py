from decimal import Decimal

import pytest
from pydantic import ValidationError

from schemas.locations import LocationCreate
from services.locations import to_place
from tests.factories import location_payload


def test_location_create_rounds_decimal_coordinates_to_6_places():
    data = LocationCreate(**location_payload(latitude=Decimal("-1.9497123")))

    assert data.latitude == Decimal("-1.949712")


def test_search_result_with_html_in_name_is_skipped():
    item = {
        "osm_type": "node",
        "osm_id": 1,
        "name": "<b>Westlands</b>",
        "display_name": "Westlands, Nairobi, Nairobi County, Kenya",
        "lat": "-1.95",
        "lon": "30.11",
        "address": {"county": "Westlands", "state": "Nairobi County"},
    }

    assert to_place(item) is None


def test_search_result_with_non_numeric_coordinates_is_skipped():
    item = {
        "osm_type": "node",
        "osm_id": 1,
        "name": "Westlands",
        "display_name": "Westlands, Nairobi, Nairobi County, Kenya",
        "lat": "abc",
        "lon": "30.11",
        "address": {"county": "Westlands", "state": "Nairobi County"},
    }

    assert to_place(item) is None


def test_search_result_without_coordinates_is_skipped():
    item = {
        "osm_type": "node",
        "osm_id": 1,
        "name": "Westlands",
        "display_name": "Westlands, Nairobi, Nairobi County, Kenya",
        "lat": None,
        "lon": None,
        "address": {"county": "Westlands", "state": "Nairobi County"},
    }

    assert to_place(item) is None


def test_place_name_that_is_a_number_is_rejected():
    with pytest.raises(ValidationError):
        LocationCreate(**location_payload(name=123))
