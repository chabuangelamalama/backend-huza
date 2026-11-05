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
        token_version=user.token_version,
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


def accept(client, enquiry_id, user):
    return client.post(f"{URL}/{enquiry_id}/accept", headers=auth(user))


def test_seller_accepts_enquiry_and_it_becomes_agreed(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]

    response = accept(client, enquiry_id, world.seller_user)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == EnquiryStatus.AGREED.value
    assert body["accepted_at"] is not None
    assert body["first_response_at"] is not None


def test_buyer_cannot_accept_their_own_enquiry(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]
    assert accept(client, enquiry_id, world.buyer_user).status_code == 403


def test_outsider_and_unknown_enquiry_get_404_on_accept(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]
    assert accept(client, enquiry_id, world.other_user).status_code == 404
    assert accept(client, uuid.uuid4(), world.seller_user).status_code == 404


def test_enquiry_can_only_be_accepted_once(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]
    assert accept(client, enquiry_id, world.seller_user).status_code == 200
    assert accept(client, enquiry_id, world.seller_user).status_code == 409


def test_accept_needs_a_login(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]
    assert client.post(f"{URL}/{enquiry_id}/accept").status_code == 401


def test_api_enquiry_is_payable_like_the_seed(client, world, session):
    """Create -> accept through the API gives an enquiry the buyer can pay."""
    from models.business import PayoutNetwork
    from models.enquiry import Enquiry
    from services.payment_service import PaymentService
    from tests.test_payments import make_settings

    world.seller.payout_phone = "254708374149"
    world.seller.payout_network = PayoutNetwork.MPESA
    world.buyer.contact_phone = "254708374149"
    session.commit()

    enquiry_id = create(client, world).json()["enquiry_id"]
    assert accept(client, enquiry_id, world.seller_user).status_code == 200

    enquiry = session.get(Enquiry, uuid.UUID(enquiry_id))
    session.refresh(enquiry)
    assert enquiry.status == EnquiryStatus.AGREED
    assert enquiry.total_amount == Decimal("50")

    service = PaymentService(session, None, make_settings())
    service._check_can_pay(world.buyer_user, enquiry, "254708374149")


def test_total_must_be_whole_shillings(client, world):
    response = create(client, world, quantity="3.000", unit_price="10.5000")
    assert response.status_code == 422
    assert "31.5 KES" in response.json()["detail"]


def test_fractional_inputs_with_whole_total_are_allowed(client, world):
    response = create(client, world, quantity="2.500", unit_price="4.0000")
    assert response.status_code == 201
    assert Decimal(response.json()["total_amount"]) == Decimal("10")


def name_and_contact(world, session):
    world.seller.display_name = "Organic Waste Processors"
    world.seller.contact_phone = "254711000111"
    world.seller.contact_email = "seller@example.ke"
    world.buyer.display_name = None
    world.buyer.business_legal_name = "Eco Briquettes Ltd"
    world.buyer.contact_phone = "254722000222"
    world.buyer.contact_email = "buyer@example.ke"
    session.commit()


def test_enquiry_shows_both_business_names(client, world, session):
    name_and_contact(world, session)

    body = create(client, world).json()

    assert body["seller"]["name"] == "Organic Waste Processors"
    assert body["buyer"]["name"] == "Eco Briquettes Ltd"  # falls back to legal name
    assert body["seller"]["business_id"] == str(world.seller.business_id)


def test_contact_details_are_hidden_until_the_seller_accepts(client, world, session):
    name_and_contact(world, session)
    enquiry_id = create(client, world).json()["enquiry_id"]

    before = client.get(f"{URL}/{enquiry_id}", headers=auth(world.buyer_user)).json()
    assert before["seller"]["phone"] is None and before["seller"]["email"] is None
    assert before["buyer"]["phone"] is None and before["buyer"]["email"] is None

    accept(client, enquiry_id, world.seller_user)

    after = client.get(f"{URL}/{enquiry_id}", headers=auth(world.buyer_user)).json()
    assert after["seller"]["phone"] == "254711000111"
    assert after["seller"]["email"] == "seller@example.ke"
    seller_view = client.get(f"{URL}/{enquiry_id}", headers=auth(world.seller_user))
    assert seller_view.json()["buyer"]["email"] == "buyer@example.ke"


def test_enquiry_list_includes_business_names(client, world, session):
    name_and_contact(world, session)
    create(client, world)

    rows = client.get(URL, headers=auth(world.seller_user)).json()

    assert rows[0]["buyer"]["name"] == "Eco Briquettes Ltd"
    assert rows[0]["buyer"]["phone"] is None


def test_enquiry_keeps_the_buyers_message(client, world):
    body = create(
        client, world, message="  Can you deliver to Ruiru on Friday?  "
    ).json()
    assert body["message"] == "Can you deliver to Ruiru on Friday?"


def test_blank_or_missing_message_is_null(client, world, session):
    assert create(client, world, message="   ").json()["message"] is None


def test_message_has_a_length_limit(client, world):
    assert create(client, world, message="x" * 1001).status_code == 422


def close(client, enquiry_id, user, **body):
    values = {"status": "CANCELLED", "failure_reason": "PRICE"}
    values.update(body)
    return client.post(f"{URL}/{enquiry_id}/close", json=values, headers=auth(user))


def test_buyer_cancels_an_open_enquiry(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]

    response = close(client, enquiry_id, world.buyer_user)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CANCELLED"
    assert body["failure_reason"] == "PRICE"
    assert body["closed_at"] is not None


def test_seller_declines_and_it_counts_as_a_response(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]

    body = close(
        client,
        enquiry_id,
        world.seller_user,
        status="UNSUCCESSFUL",
        failure_reason="DECLINED",
    ).json()

    assert body["status"] == "UNSUCCESSFUL"
    assert body["failure_reason"] == "DECLINED"
    assert body["first_response_at"] is not None


def test_agreed_enquiry_can_be_closed_as_unsuccessful(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]
    accept(client, enquiry_id, world.seller_user)

    response = close(
        client,
        enquiry_id,
        world.buyer_user,
        status="UNSUCCESSFUL",
        failure_reason="TRANSPORT",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "UNSUCCESSFUL"


def test_closed_enquiry_frees_the_listing_for_a_new_one(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]
    close(client, enquiry_id, world.buyer_user)
    assert create(client, world).status_code == 201


def test_outsider_cannot_close(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]
    assert close(client, enquiry_id, world.other_user).status_code == 404
    assert close(client, uuid.uuid4(), world.buyer_user).status_code == 404


def test_enquiry_cannot_be_closed_twice(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]
    close(client, enquiry_id, world.buyer_user)
    response = close(client, enquiry_id, world.seller_user)
    assert response.status_code == 409
    assert "cancelled" in response.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"status": "COMPLETED", "failure_reason": "PRICE"},
        {"status": "CANCELLED"},
        {"status": "CANCELLED", "failure_reason": "NOT_A_REASON"},
        {"status": "CANCELLED", "failure_reason": "PRICE", "extra": 1},
    ],
)
def test_close_rejects_invalid_bodies(client, world, body):
    enquiry_id = create(client, world).json()["enquiry_id"]
    response = client.post(
        f"{URL}/{enquiry_id}/close", json=body, headers=auth(world.buyer_user)
    )
    assert response.status_code == 422


def test_paid_enquiry_cannot_be_closed(client, world, session):
    from models.enquiry import Enquiry

    enquiry_id = create(client, world).json()["enquiry_id"]
    session.get(Enquiry, uuid.UUID(enquiry_id)).status = EnquiryStatus.PAID
    session.commit()

    response = close(client, enquiry_id, world.buyer_user)

    assert response.status_code == 409
    assert "refund" in response.json()["detail"]


def test_enquiry_cannot_be_closed_while_a_payment_is_in_progress(
    client, world, session
):
    from models.enquiry import Enquiry
    from tests.test_models import make_payment

    enquiry_id = create(client, world).json()["enquiry_id"]
    accept(client, enquiry_id, world.seller_user)
    make_payment(
        session, session.get(Enquiry, uuid.UUID(enquiry_id)), amount=Decimal("50")
    )
    session.commit()

    response = close(client, enquiry_id, world.buyer_user)

    assert response.status_code == 409
    assert "in progress" in response.json()["detail"]


def test_close_needs_a_login(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]
    response = client.post(
        f"{URL}/{enquiry_id}/close",
        json={"status": "CANCELLED", "failure_reason": "PRICE"},
    )
    assert response.status_code == 401


def test_listing_shows_seller_name_and_location(client, world, session):
    world.seller.display_name = "Organic Waste Processors"
    session.commit()
    headers = auth(world.buyer_user)

    one = client.get(f"/listing/{world.listing.listing_id}", headers=headers)
    many = client.get("/listing/", headers=headers)

    assert one.status_code == 200 and many.status_code == 200
    for body in (one.json(), many.json()[0]):
        assert body["business_name"] == "Organic Waste Processors"
        assert body["location"]["location_id"] == str(world.location.location_id)
        assert body["location"]["name"] == world.location.name
        assert body["location"]["county"] == world.location.county
        assert "phone" not in str(body) and "email" not in str(body)


def test_my_listings_show_business_name_and_location(client, world):
    response = client.get("/listing/mine", headers=auth(world.seller_user))
    assert response.status_code == 200
    body = response.json()[0]
    assert body["business_name"] == world.seller.public_name
    assert body["location"]["name"] == world.location.name


def notifications(session, user):
    from sqlalchemy import select

    from models.notification import Notification

    rows = session.scalars(
        select(Notification).where(Notification.user_id == user.user_id)
    )
    return [(n.event_type.value, str(n.enquiry_id)) for n in rows]


def test_new_enquiry_notifies_the_seller_only(client, world, session):
    enquiry_id = create(client, world).json()["enquiry_id"]

    assert notifications(session, world.seller_user) == [
        ("ENQUIRY_RECEIVED", enquiry_id)
    ]
    assert notifications(session, world.buyer_user) == []


def test_accepting_notifies_the_buyer(client, world, session):
    enquiry_id = create(client, world).json()["enquiry_id"]
    accept(client, enquiry_id, world.seller_user)

    assert notifications(session, world.buyer_user) == [("STATUS_CHANGED", enquiry_id)]


def test_seller_declining_notifies_the_buyer(client, world, session):
    enquiry_id = create(client, world).json()["enquiry_id"]
    close(
        client,
        enquiry_id,
        world.seller_user,
        status="UNSUCCESSFUL",
        failure_reason="DECLINED",
    )

    assert notifications(session, world.buyer_user) == [("STATUS_CHANGED", enquiry_id)]


def test_buyer_cancelling_notifies_the_seller(client, world, session):
    enquiry_id = create(client, world).json()["enquiry_id"]
    close(client, enquiry_id, world.buyer_user)

    assert notifications(session, world.seller_user) == [
        ("ENQUIRY_RECEIVED", enquiry_id),
        ("STATUS_CHANGED", enquiry_id),
    ]
    assert notifications(session, world.buyer_user) == []


def test_rejected_actions_send_no_notification(client, world, session):
    enquiry_id = create(client, world).json()["enquiry_id"]
    accept(client, enquiry_id, world.buyer_user)  # 403: only the seller accepts
    close(client, enquiry_id, world.other_user)  # 404: not a participant

    assert notifications(session, world.buyer_user) == []
    assert notifications(session, world.other_user) == []


def test_notification_shows_up_in_the_notifications_api(client, world):
    enquiry_id = create(client, world).json()["enquiry_id"]

    rows = client.get("/notifications", headers=auth(world.seller_user)).json()

    assert [(r["event_type"], r["enquiry_id"], r["is_read"]) for r in rows] == [
        ("ENQUIRY_RECEIVED", enquiry_id, False)
    ]


@pytest.mark.parametrize("path", [URL, "/notifications", "/price-guides"])
def test_token_from_before_logout_is_refused(client, world, session, path):
    headers = auth(world.buyer_user)
    assert client.get(path, headers=headers).status_code == 200

    world.buyer_user.token_version += 1  # what logout and password change do
    session.commit()

    assert client.get(path, headers=headers).status_code == 401
