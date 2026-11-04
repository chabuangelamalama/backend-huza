import pytest

from core import nominatim
from services.locations import to_place
from tests.factories import auth, make_user

WESTLANDS = {
    "osm_type": "node",
    "osm_id": 123456,
    "name": "Westlands",
    "display_name": "Westlands, Westlands Sub County, Nairobi County, Kenya",
    "lat": "-1.2675000",
    "lon": "36.8108000",
    "address": {
        "suburb": "Westlands",
        "county": "Westlands Sub County",
        "state": "Nairobi County",
        "country": "Kenya",
        "country_code": "ke",
    },
}

NO_COUNTY = {
    "osm_type": "relation",
    "osm_id": 999,
    "name": "Kenya",
    "display_name": "Kenya",
    "lat": "0.17",
    "lon": "37.90",
    "address": {"country": "Kenya", "country_code": "ke"},
}


@pytest.fixture
def user(session):
    return make_user(session)


@pytest.fixture
def fake_search(monkeypatch):
    calls = []

    def fake(query, limit=5):
        calls.append((query, limit))
        return [WESTLANDS, NO_COUNTY]

    monkeypatch.setattr(nominatim, "search", fake)
    return calls


def test_places_search_returns_results_shaped_like_a_business_location(
    client, user, fake_search
):
    response = client.get(
        "/businesses/places", params={"q": " Westlands "}, headers=auth(user)
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "osm_type": "NODE",
            "osm_id": 123456,
            "name": "Westlands",
            "display_name": "Westlands, Westlands Sub County, Nairobi County, Kenya",
            "latitude": -1.2675,
            "longitude": 36.8108,
            "sub_county": "Westlands",
            "county": "Nairobi",
        }
    ]
    assert fake_search == [("Westlands", 5)]


def test_places_route_is_not_treated_as_a_business_id(client, user, fake_search):
    response = client.get(
        "/businesses/places", params={"q": "Westlands"}, headers=auth(user)
    )

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_places_search_without_token_returns_401(client, fake_search):
    response = client.get("/businesses/places", params={"q": "Westlands"})

    assert response.status_code == 401
    assert fake_search == []


def test_places_search_with_one_letter_returns_422(client, user, fake_search):
    response = client.get("/businesses/places", params={"q": "R"}, headers=auth(user))

    assert response.status_code == 422


def test_places_search_returns_503_with_message_when_openstreetmap_is_down(
    client, user, monkeypatch
):
    def broken(query, limit=5):
        raise nominatim.NominatimError("down")

    monkeypatch.setattr(nominatim, "search", broken)

    response = client.get(
        "/businesses/places", params={"q": "Westlands"}, headers=auth(user)
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Place search is not available right now. Try again soon."
    )


def test_search_result_without_county_or_sub_county_is_skipped():
    assert to_place(NO_COUNTY) is None


@pytest.mark.parametrize(
    "sub_county",
    ["Naivasha Sub County", "Naivasha Sub-County", "Naivasha Subcounty", "Naivasha"],
)
def test_county_and_sub_county_names_drop_their_suffixes(sub_county):
    item = {**WESTLANDS, "address": {"county": sub_county, "state": "Nakuru County"}}

    place = to_place(item)

    assert place is not None
    assert place.sub_county == "Naivasha"
    assert place.county == "Nakuru"


def test_sub_county_named_as_a_constituency_drops_the_word_constituency():
    item = {
        **WESTLANDS,
        "address": {"county": "Nyali Constituency", "state": "Mombasa County"},
    }

    place = to_place(item)

    assert place is not None
    assert place.sub_county == "Nyali"
    assert place.county == "Mombasa"


def test_sub_county_falls_back_to_state_district_field():
    item = {
        **WESTLANDS,
        "address": {"state_district": "Kisumu Central", "state": "Kisumu County"},
    }

    place = to_place(item)

    assert place is not None
    assert place.sub_county == "Kisumu Central"
    assert place.county == "Kisumu"


def test_sub_county_falls_back_to_city_when_openstreetmap_has_no_sub_county():
    item = {**WESTLANDS, "address": {"city": "Eldoret", "state": "Uasin Gishu County"}}

    place = to_place(item)

    assert place is not None
    assert place.sub_county == "Eldoret"
    assert place.county == "Uasin Gishu"


def test_place_without_a_sub_county_or_town_is_skipped():
    item = {**WESTLANDS, "address": {"state": "Nairobi County", "country": "Kenya"}}

    assert to_place(item) is None


def test_missing_name_falls_back_to_first_part_of_display_name():
    place = to_place({**WESTLANDS, "name": ""})

    assert place is not None
    assert place.name == "Westlands"
