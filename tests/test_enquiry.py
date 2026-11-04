import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.config import Settings
from core.security import create_access_token
from models.business import ApprovalStatus, BusinessRole
from models.enquiry import EnquiryStatus
from models.listing import ListingStatus, Unit
from models.user import UserRole
from tests.test_models import make_business, make_listing, make_location, make_user

URL = "/enquiries"
TEST_SETTINGS = Settings(
    _env_file=None,
    database_url="sqlite://",
    jwt_secret="test-secret-that-is-at-least-32-characters-long",
    max_failed_logins=3,
    lockout_minutes=15,
    environment="test",
)


@pytest.fixture
def world(session):
    location = make_location(session)
    seller = make_business(
        session,
        location,
        approval_status=ApprovalStatus.APPROVED,
    )
    buyer = make_business(
        session,
        location,
        role=BusinessRole.BUYER,
        approval_status=ApprovalStatus.APPROVED,
    )
    other_buyer = make_business(
        session,
        location,
        role=BusinessRole.BUYER,
        approval_status=ApprovalStatus.APPROVED,
    )
    listing = make_listing(
        session,
        seller,
        location,
        status=ListingStatus.PUBLISHED,
    )
    return SimpleNamespace(
        location=location,
        seller=seller,
        buyer=buyer,
        other_buyer=other_buyer,
        listing=listing,
        seller_user=make_user(session, seller),
        buyer_user=make_user(session, buyer),
        other_user=make_user(session, other_buyer),
        admin=make_user(session, role=UserRole.ADMIN),
    )


def auth(user):
    token = create_access_token(
        user.user_id,
        user.user_role,
        settings=TEST_SETTINGS,
    )
    return {"Authorization": f"Bearer {token}"}


def payload(world, **changes):
    values = {
        "listing_id": str(world.listing.listing_id),
        "buyer_business_id": str(world.buyer.business_id),
        "seller_business_id": str(world.seller.business_id),
        "quantity": "10.000",
        "unit": Unit.KILOGRAM.value,
        "unit_price": "5.0000",
    }
    values.update(changes)
    return values


def create(client, world, user=None, **changes):
    return client.post(
        URL,
        json=payload(world, **changes),
        headers=auth(user or world.buyer_user),
    )


def test_create_enquiry(client, world):
    response = create(client, world)

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == EnquiryStatus.ENQUIRY.value
    assert data["quantity"] == "10.000"
    assert data["unit"] == Unit.KILOGRAM.value
    assert data["unit_price"] == "5.0000"
    assert Decimal(data["total_amount"]) == Decimal("50.0000")
    assert data["enquiry_id"]
    assert data["created_at"]


def test_create_enquiry_needs_a_login(client, world):
    response = client.post(URL, json=payload(world))
    assert response.status_code == 401


def test_the_old_versioned_prefix_still_works(client, world):
    response = client.post(
        "/api/v1/enquiries",
        json=payload(world),
        headers=auth(world.buyer_user),
    )
    assert response.status_code == 201


def test_admin_cannot_create_an_enquiry(client, world):
    response = create(client, world, world.admin)
    assert response.status_code == 403
    assert "only business accounts" in response.json()["detail"]


def test_unapproved_business_cannot_create_an_enquiry(client, world, session):
    world.buyer.approval_status = ApprovalStatus.PENDING
    session.flush()

    response = create(client, world)
    assert response.status_code == 403
    assert "not approved" in response.json()["detail"]


def test_a_business_cannot_create_an_enquiry_for_another_buyer(client, world):
    response = create(
        client,
        world,
        buyer_business_id=str(world.other_buyer.business_id),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "You can only create enquiries for your own business."
    )


def test_unknown_listing_gives_404(client, world):
    response = create(client, world, listing_id=str(uuid.uuid4()))
    assert response.status_code == 404
    assert response.json()["detail"] == "Listing not found."


def test_seller_must_own_the_listing(client, world):
    response = create(
        client,
        world,
        seller_business_id=str(world.other_buyer.business_id),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "The seller does not own this listing."


def test_a_business_cannot_enquire_about_its_own_listing(client, world):
    response = create(
        client,
        world,
        world.seller_user,
        buyer_business_id=str(world.seller.business_id),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "A business cannot enquire about its own listing."
    )


def test_unpublished_listing_cannot_be_enquired_about(client, world, session):
    world.listing.status = ListingStatus.PAUSED
    session.flush()

    response = create(client, world)
    assert response.status_code == 400
    assert response.json()["detail"] == ("This listing is not available for enquiries.")


def test_duplicate_open_enquiry_gives_409(client, world):
    assert create(client, world).status_code == 201

    response = create(client, world)
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "An open enquiry for this listing already exists."
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": "0"},
        {"quantity": "-1"},
        {"unit_price": "0"},
        {"unit_price": "-1"},
        {"unit": "kg"},
        {"colour": "green"},
    ],
)
def test_create_rejects_invalid_values(client, world, changes):
    response = create(client, world, **changes)
    assert response.status_code == 422


def test_list_only_shows_enquiries_for_my_business(client, world):
    assert create(client, world).status_code == 201

    buyer_list = client.get(URL, headers=auth(world.buyer_user))
    seller_list = client.get(URL, headers=auth(world.seller_user))
    other_list = client.get(URL, headers=auth(world.other_user))
    admin_list = client.get(URL, headers=auth(world.admin))

    assert buyer_list.status_code == 200
    assert seller_list.status_code == 200
    assert len(buyer_list.json()) == 1
    assert len(seller_list.json()) == 1
    assert other_list.json() == []

    assert admin_list.status_code == 200
    assert len(admin_list.json()) == 1


def test_list_can_be_filtered_and_paged(client, world, session):
    assert create(client, world).status_code == 201
    second_listing = make_listing(
        session,
        world.seller,
        world.location,
        status=ListingStatus.PUBLISHED,
        material_or_product="Second sawdust lot",
    )
    second = payload(world, listing_id=str(second_listing.listing_id))
    assert (
        client.post(URL, json=second, headers=auth(world.buyer_user)).status_code == 201
    )

    paged = client.get(
        URL,
        params={"limit": 1, "offset": 1},
        headers=auth(world.buyer_user),
    )
    assert paged.status_code == 200
    assert len(paged.json()) == 1

    enquiry_only = client.get(
        URL,
        params={"status": EnquiryStatus.ENQUIRY.value},
        headers=auth(world.buyer_user),
    )
    assert len(enquiry_only.json()) == 2

    cancelled_only = client.get(
        URL,
        params={"status": EnquiryStatus.CANCELLED.value},
        headers=auth(world.buyer_user),
    )
    assert cancelled_only.json() == []


def test_get_enquiry_is_limited_to_participants(client, world):
    created = create(client, world).json()

    buyer_response = client.get(
        f"{URL}/{created['enquiry_id']}",
        headers=auth(world.buyer_user),
    )
    seller_response = client.get(
        f"{URL}/{created['enquiry_id']}",
        headers=auth(world.seller_user),
    )
    other_response = client.get(
        f"{URL}/{created['enquiry_id']}",
        headers=auth(world.other_user),
    )
    admin_response = client.get(
        f"{URL}/{created['enquiry_id']}",
        headers=auth(world.admin),
    )

    assert buyer_response.status_code == 200
    assert seller_response.status_code == 200
    assert admin_response.status_code == 200
    assert other_response.status_code == 404
    assert other_response.json()["detail"] == "Enquiry not found."


def test_get_unknown_enquiry_gives_404(client, world):
    response = client.get(f"{URL}/{uuid.uuid4()}", headers=auth(world.buyer_user))
    assert response.status_code == 404


def test_get_malformed_enquiry_id_gives_422(client, world):
    response = client.get(f"{URL}/not-a-uuid", headers=auth(world.buyer_user))
    assert response.status_code == 422


def test_list_and_get_need_a_login(client, world):
    assert client.get(URL).status_code == 401
    assert client.get(f"{URL}/{uuid.uuid4()}").status_code == 401
