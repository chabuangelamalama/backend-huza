import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import create_access_token
from main import app
from models.user import UserRole
from models.listing import Stream, Unit
from tests.price_guide_helpers import make_admin, make_business_user, make_guide

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
def admin(session):
    return make_admin(session)


@pytest.fixture
def seller(session):
    return make_business_user(session)


@pytest.fixture
def unapproved_seller(session):
    return make_business_user(session, email="pending@example.rw", approval=None)


def test_listing_needs_a_login(client):
    assert client.get(URL).status_code == 401


def test_a_bad_token_is_rejected(client):
    response = client.get(URL, headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


def test_an_expired_token_is_rejected(client, admin):
    token = create_access_token(admin.user_id, UserRole.ADMIN, expires_minutes=-5)
    response = client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_a_business_user_can_read_the_guides(client, seller, session):
    make_guide(session)
    response = client.get(URL, headers=headers_for(seller))
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


def test_a_business_user_cannot_create_a_guide(client, seller):
    response = client.post(URL, json=new_guide_body(), headers=headers_for(seller))
    assert response.status_code == 403
    assert "cannot create price guides" in response.json()["detail"]


def test_an_admin_can_create_a_guide(client, admin):
    response = client.post(URL, json=new_guide_body(), headers=headers_for(admin))
    assert response.status_code == 201
    body = response.json()
    assert body["material"] == "Pine sawdust"
    assert Decimal(body["min_price"]) == Decimal("30")
    assert body["guide_id"]


def test_an_admin_sees_who_created_a_guide(client, admin):
    response = client.post(URL, json=new_guide_body(), headers=headers_for(admin))
    assert response.json()["created_by"] == str(admin.user_id)


def test_a_business_user_does_not_see_who_created_a_guide(
    client, admin, seller, session
):
    guide = make_guide(session, created_by=admin.user_id)
    one = client.get(f"{URL}/{guide.guide_id}", headers=headers_for(seller))
    assert one.status_code == 200
    assert one.json()["created_by"] is None
    many = client.get(URL, headers=headers_for(seller))
    assert many.json()[0]["created_by"] is None


def test_creating_with_max_price_below_min_price_fails(client, admin):
    body = new_guide_body(min_price=60, max_price=30)
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 422


def test_creating_with_a_future_date_fails(client, admin):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    body = new_guide_body(source_date=tomorrow)
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 422


def test_creating_with_a_missing_field_fails(client, admin):
    body = new_guide_body()
    del body["source"]
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 422


def test_creating_with_an_unknown_field_fails(client, admin):
    body = new_guide_body(colour="red")
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 422


def test_a_token_for_a_user_that_does_not_exist_cannot_create(client):
    token = create_access_token(uuid.uuid4(), UserRole.ADMIN)
    response = client.post(
        URL, json=new_guide_body(), headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_creating_with_a_valid_grade_saves_it_in_lowercase(client, admin):
    body = new_guide_body(grade="Dry")
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 201
    assert response.json()["grade"] == "dry"


def test_creating_with_a_grade_from_another_stream_fails(client, admin):
    body = new_guide_body(grade="hard")
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 422


def test_creating_a_glass_guide_with_a_glass_grade_works(client, admin):
    body = new_guide_body(
        stream="GLASS", material="Cullet", unit="TONNE", grade="clear"
    )
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 201
    assert response.json()["grade"] == "clear"


def test_creating_the_same_guide_twice_gives_409(client, admin):
    first = client.post(URL, json=new_guide_body(), headers=headers_for(admin))
    assert first.status_code == 201
    second = client.post(URL, json=new_guide_body(), headers=headers_for(admin))
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]


def test_the_same_material_in_other_letters_is_still_a_duplicate(client, admin):
    client.post(URL, json=new_guide_body(), headers=headers_for(admin))
    response = client.post(
        URL, json=new_guide_body(material="PINE SAWDUST"), headers=headers_for(admin)
    )
    assert response.status_code == 409


def test_the_same_material_with_another_grade_is_allowed(client, admin):
    client.post(URL, json=new_guide_body(grade="dry"), headers=headers_for(admin))
    response = client.post(
        URL, json=new_guide_body(grade="wet"), headers=headers_for(admin)
    )
    assert response.status_code == 201


def test_the_same_material_in_another_district_is_allowed(client, admin):
    client.post(URL, json=new_guide_body(district="Kigali"), headers=headers_for(admin))
    response = client.post(
        URL, json=new_guide_body(district="Huye"), headers=headers_for(admin)
    )
    assert response.status_code == 201


def test_the_same_district_in_other_letters_is_a_duplicate(client, admin):
    client.post(URL, json=new_guide_body(district="Kigali"), headers=headers_for(admin))
    response = client.post(
        URL, json=new_guide_body(district="KIGALI"), headers=headers_for(admin)
    )
    assert response.status_code == 409


def test_a_different_price_or_date_does_not_make_a_guide_new(client, admin):
    client.post(URL, json=new_guide_body(), headers=headers_for(admin))
    other_day = (date.today() - timedelta(days=30)).isoformat()
    response = client.post(
        URL,
        json=new_guide_body(min_price=10, max_price=20, source_date=other_day),
        headers=headers_for(admin),
    )
    assert response.status_code == 409


def test_the_list_can_be_filtered(client, admin, session):
    make_guide(session)
    make_guide(session, stream=Stream.GLASS, material="Cullet", unit=Unit.TONNE)
    response = client.get(
        URL, params={"stream": "GLASS", "material": "cul"}, headers=headers_for(admin)
    )
    assert [guide["material"] for guide in response.json()] == ["Cullet"]


@pytest.mark.parametrize("limit", [0, 101])
def test_the_list_limit_must_be_between_1_and_100(client, admin, limit):
    response = client.get(URL, params={"limit": limit}, headers=headers_for(admin))
    assert response.status_code == 422


def test_one_guide_can_be_read(client, admin, session):
    guide = make_guide(session)
    response = client.get(f"{URL}/{guide.guide_id}", headers=headers_for(admin))
    assert response.status_code == 200
    assert response.json()["guide_id"] == str(guide.guide_id)


def test_reading_an_unknown_guide_gives_404(client, admin):
    response = client.get(f"{URL}/{uuid.uuid4()}", headers=headers_for(admin))
    assert response.status_code == 404
    assert response.json()["detail"] == "Price guide not found."


def test_reading_a_malformed_id_gives_422(client, admin):
    response = client.get(f"{URL}/not-an-id", headers=headers_for(admin))
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("price", "position"),
    [(20, "below"), (30, "within"), (45, "within"), (90, "above")],
)
def test_lookup_says_where_a_price_sits(client, seller, session, price, position):
    make_guide(session)
    response = client.get(
        LOOKUP,
        params={
            "stream": "SAWDUST",
            "material": "pine sawdust",
            "unit": "KILOGRAM",
            "price": price,
        },
        headers=headers_for(seller),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["position"] == position
    assert body["guide"]["material"] == "Pine sawdust"


def test_lookup_without_a_price_still_returns_the_guide(client, seller, session):
    make_guide(session)
    response = client.get(
        LOOKUP,
        params={"stream": "SAWDUST", "material": "Pine sawdust", "unit": "KILOGRAM"},
        headers=headers_for(seller),
    )
    body = response.json()
    assert body["position"] is None
    assert body["guide"] is not None


def test_lookup_prefers_the_guide_with_the_matching_grade(client, seller, session):
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
        headers=headers_for(seller),
    )
    body = response.json()
    assert body["guide"]["grade"] == "wet"
    assert body["position"] == "within"


def test_lookup_with_no_matching_guide_returns_nothing(client, seller):
    response = client.get(
        LOOKUP,
        params={"stream": "GLASS", "material": "Cullet", "unit": "TONNE", "price": 5},
        headers=headers_for(seller),
    )
    assert response.status_code == 200
    assert response.json() == {"guide": None, "position": None}


def test_lookup_hides_the_creator_from_a_business_user(client, admin, seller, session):
    make_guide(session, created_by=admin.user_id)
    response = client.get(
        LOOKUP,
        params={"stream": "SAWDUST", "material": "Pine sawdust", "unit": "KILOGRAM"},
        headers=headers_for(seller),
    )
    assert response.json()["guide"]["created_by"] is None


def test_lookup_price_must_be_above_zero(client, seller):
    response = client.get(
        LOOKUP,
        params={
            "stream": "SAWDUST",
            "material": "Pine sawdust",
            "unit": "KILOGRAM",
            "price": 0,
        },
        headers=headers_for(seller),
    )
    assert response.status_code == 422


def test_lookup_needs_a_login(client):
    response = client.get(
        LOOKUP,
        params={"stream": "SAWDUST", "material": "Pine sawdust", "unit": "KILOGRAM"},
    )
    assert response.status_code == 401


def test_an_admin_can_update_a_guide(client, admin, session):
    guide = make_guide(session)
    response = client.patch(
        f"{URL}/{guide.guide_id}", json={"max_price": 80}, headers=headers_for(admin)
    )
    assert response.status_code == 200
    assert Decimal(response.json()["max_price"]) == Decimal("80")


def test_updating_with_max_price_below_min_price_fails(client, admin, session):
    guide = make_guide(session)
    response = client.patch(
        f"{URL}/{guide.guide_id}", json={"max_price": 10}, headers=headers_for(admin)
    )
    assert response.status_code == 422


def test_updating_with_nothing_gives_400(client, admin, session):
    guide = make_guide(session)
    response = client.patch(
        f"{URL}/{guide.guide_id}", json={}, headers=headers_for(admin)
    )
    assert response.status_code == 400


def test_updating_to_a_grade_from_another_stream_fails(client, admin, session):
    guide = make_guide(session, grade="dry")
    response = client.patch(
        f"{URL}/{guide.guide_id}", json={"stream": "GLASS"}, headers=headers_for(admin)
    )
    assert response.status_code == 422


def test_updating_into_a_duplicate_gives_409(client, admin, session):
    make_guide(session)
    other = make_guide(session, material="Oak sawdust")
    response = client.patch(
        f"{URL}/{other.guide_id}",
        json={"material": "Pine sawdust"},
        headers=headers_for(admin),
    )
    assert response.status_code == 409


def test_a_guide_can_be_updated_without_clashing_with_itself(client, admin, session):
    guide = make_guide(session)
    response = client.patch(
        f"{URL}/{guide.guide_id}",
        json={"material": "Pine sawdust", "min_price": 25},
        headers=headers_for(admin),
    )
    assert response.status_code == 200


def test_a_business_user_cannot_update_a_guide(client, seller, session):
    guide = make_guide(session)
    response = client.patch(
        f"{URL}/{guide.guide_id}", json={"max_price": 80}, headers=headers_for(seller)
    )
    assert response.status_code == 403


def test_updating_an_unknown_guide_gives_404(client, admin):
    response = client.patch(
        f"{URL}/{uuid.uuid4()}", json={"max_price": 80}, headers=headers_for(admin)
    )
    assert response.status_code == 404


def test_an_admin_can_delete_a_guide(client, admin, session):
    guide = make_guide(session)
    response = client.delete(f"{URL}/{guide.guide_id}", headers=headers_for(admin))
    assert response.status_code == 204
    again = client.get(f"{URL}/{guide.guide_id}", headers=headers_for(admin))
    assert again.status_code == 404


def test_a_business_user_cannot_delete_a_guide(client, seller, session):
    guide = make_guide(session)
    response = client.delete(f"{URL}/{guide.guide_id}", headers=headers_for(seller))
    assert response.status_code == 403


def test_deleting_an_unknown_guide_gives_404(client, admin):
    response = client.delete(f"{URL}/{uuid.uuid4()}", headers=headers_for(admin))
    assert response.status_code == 404
