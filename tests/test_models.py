import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from models import (
    Business,
    Enquiry,
    Listing,
    Location,
    Notification,
    Payment,
    PriceGuide,
    User,
)
from models.business import (
    ApprovalStatus,
    BusinessRole,
    BusinessType,
    PayoutNetwork,
    SupplierKind,
)
from models.enquiry import EnquiryStatus, FailureReason
from models.listing import ListingStatus, ListingType, Stream, Unit
from models.location import OsmType
from models.notification import NotificationEvent
from models.payment import PaymentStatus, PayoutStatus
from models.user import UserRole


def make_location(session, osm_id=1, osm_type=OsmType.NODE):
    location = Location(
        osm_type=osm_type,
        osm_id=osm_id,
        name="Remera",
        display_name="Remera, Gasabo, Kigali City, Rwanda",
        latitude=Decimal("-1.956000"),
        longitude=Decimal("30.113000"),
        district="Gasabo",
        province="Kigali City",
    )
    session.add(location)
    session.flush()
    return location


def make_business(
    session,
    location,
    role=BusinessRole.SUPPLIER,
    business_type=BusinessType.BUSINESS,
    **changes,
):
    values = dict(
        business_legal_name="Kigali Timber Works",
        business_role=role,
        business_type=business_type,
        location_id=location.location_id,
        streams=["SAWDUST"],
        contact_email="info@example.rw",
    )
    values.update(changes)
    business = Business(**values)
    session.add(business)
    session.flush()
    return business


def make_user(session, business=None, role=UserRole.BUSINESS_USER, **changes):
    values = dict(
        first_name="Jean",
        last_name="Habimana",
        email=f"{uuid.uuid4().hex}@example.rw",
        password_hash="x",
    )
    if business is not None:
        values["business_id"] = business.business_id
    if role is not None:
        values["user_role"] = role
    values.update(changes)
    user = User(**values)
    session.add(user)
    session.flush()
    return user


def make_listing(session, business, location, **changes):
    values = dict(
        business_id=business.business_id,
        listing_type=ListingType.RAW_BYPRODUCT,
        stream=Stream.SAWDUST,
        material_or_product="Pine sawdust",
        quantity=Decimal("1000"),
        unit=Unit.KILOGRAM,
        unit_price=Decimal("50"),
        location_id=location.location_id,
    )
    values.update(changes)
    listing = Listing(**values)
    session.add(listing)
    session.flush()
    return listing


def make_enquiry(session, listing, buyer, **changes):
    values = dict(
        listing_id=listing.listing_id,
        buyer_business_id=buyer.business_id,
        seller_business_id=listing.business_id,
        quantity=Decimal("100"),
        unit=Unit.KILOGRAM,
        unit_price=Decimal("50"),
        total_amount=Decimal("5000"),
    )
    values.update(changes)
    enquiry = Enquiry(**values)
    session.add(enquiry)
    session.flush()
    return enquiry


def make_open_enquiry(session):
    location = make_location(session)
    seller = make_business(session, location)
    buyer = make_business(session, location, role=BusinessRole.BUYER)
    listing = make_listing(session, seller, location)
    return make_enquiry(session, listing, buyer)


def make_payment(session, enquiry, **changes):
    values = dict(
        enquiry_id=enquiry.enquiry_id,
        amount=Decimal("5000"),
        payer_phone="0788000000",
        reference_id=uuid.uuid4().hex,
    )
    values.update(changes)
    payment = Payment(**values)
    session.add(payment)
    session.flush()
    return payment


def make_notification(session, user, **changes):
    values = dict(
        user_id=user.user_id,
        event_type=NotificationEvent.ENQUIRY_RECEIVED,
    )
    values.update(changes)
    notification = Notification(**values)
    session.add(notification)
    session.flush()
    return notification


def make_price_guide(session, **changes):
    values = dict(
        stream=Stream.SAWDUST,
        material="Pine sawdust",
        unit=Unit.KILOGRAM,
        min_price=Decimal("30"),
        max_price=Decimal("60"),
        source="Kigali market survey",
        source_date=date(2026, 3, 1),
    )
    values.update(changes)
    guide = PriceGuide(**values)
    session.add(guide)
    session.flush()
    return guide


def test_all_eight_tables_exist(engine):
    names = set(inspect(engine).get_table_names())
    assert {
        "app_user",
        "business",
        "location",
        "listing",
        "price_guide",
        "enquiry",
        "payment",
        "notification",
    } <= names


def test_message_table_does_not_exist(engine):
    assert "message" not in set(inspect(engine).get_table_names())


def test_same_osm_place_is_saved_once(session):
    make_location(session, osm_id=10)
    with pytest.raises(IntegrityError):
        make_location(session, osm_id=10)


def test_same_osm_id_is_allowed_for_a_different_type(session):
    make_location(session, osm_id=10)
    way = make_location(session, osm_id=10, osm_type=OsmType.WAY)
    assert way.location_id is not None


def test_new_business_starts_pending(session):
    business = make_business(session, make_location(session))
    assert business.approval_status == ApprovalStatus.PENDING


def test_admin_cannot_have_a_business(session):
    business = make_business(session, make_location(session))
    session.add(
        User(
            business_id=business.business_id,
            first_name="Diane",
            last_name="Mukamana",
            email="diane@huza.rw",
            password_hash="x",
            user_role=UserRole.ADMIN,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_business_user_needs_a_business(session):
    session.add(
        User(
            first_name="Jean",
            last_name="Habimana",
            email="jean@example.rw",
            password_hash="x",
            user_role=UserRole.BUSINESS_USER,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_admin_without_a_business_is_allowed(session):
    admin = make_user(session, role=UserRole.ADMIN)
    assert admin.business_id is None


def test_consumer_must_be_a_buyer(session):
    location = make_location(session)
    with pytest.raises(IntegrityError):
        make_business(
            session,
            location,
            role=BusinessRole.SUPPLIER,
            business_type=BusinessType.CONSUMER,
        )


def test_business_streams_must_be_known_streams(session):
    location = make_location(session)
    with pytest.raises(IntegrityError):
        make_business(session, location, streams=["WOOD"])


def test_business_can_have_no_streams(session):
    location = make_location(session)
    business = make_business(session, location, streams=[])
    assert business.streams == []


def test_only_a_supplier_can_have_a_supplier_kind(session):
    location = make_location(session)
    with pytest.raises(IntegrityError):
        make_business(
            session,
            location,
            role=BusinessRole.BUYER,
            supplier_kind=SupplierKind.PRODUCER,
        )


def test_payout_phone_needs_a_payout_network(session):
    location = make_location(session)
    with pytest.raises(IntegrityError):
        make_business(session, location, payout_phone="0788000000")


def test_payout_phone_with_a_network_is_allowed(session):
    location = make_location(session)
    business = make_business(
        session,
        location,
        payout_phone="0788000000",
        payout_network=PayoutNetwork.MTN_MOMO,
    )
    assert business.payout_network == PayoutNetwork.MTN_MOMO


def test_user_role_defaults_to_business_user(session):
    business = make_business(session, make_location(session))
    user = make_user(session, business, role=None)
    assert user.user_role == UserRole.BUSINESS_USER


def test_email_must_be_unique(session):
    location = make_location(session)
    first = make_business(session, location)
    second = make_business(session, location)
    make_user(session, first, email="same@example.rw")
    with pytest.raises(IntegrityError):
        make_user(session, second, email="same@example.rw")


def test_a_business_has_only_one_user(session):
    business = make_business(session, make_location(session))
    make_user(session, business)
    with pytest.raises(IntegrityError):
        make_user(session, business)


def test_listing_allows_at_most_five_photos(session):
    location = make_location(session)
    business = make_business(session, location)
    listing = make_listing(session, business, location)
    listing.photos = [
        {"storage_key": str(i), "content_type": "image/jpeg", "size_bytes": 1}
        for i in range(6)
    ]
    with pytest.raises(IntegrityError):
        session.flush()


def test_new_listing_starts_as_draft(session):
    location = make_location(session)
    business = make_business(session, location)
    listing = make_listing(session, business, location)
    assert listing.status == ListingStatus.DRAFT


def test_listing_price_must_be_above_zero(session):
    location = make_location(session)
    business = make_business(session, location)
    with pytest.raises(IntegrityError):
        make_listing(session, business, location, unit_price=Decimal("0"))


def test_listing_quantity_cannot_be_negative(session):
    location = make_location(session)
    business = make_business(session, location)
    with pytest.raises(IntegrityError):
        make_listing(session, business, location, quantity=Decimal("-1"))


def test_listing_quantity_can_be_zero(session):
    location = make_location(session)
    business = make_business(session, location)
    listing = make_listing(session, business, location, quantity=Decimal("0"))
    assert listing.quantity == Decimal("0")


def test_seller_must_own_the_listing(session):
    location = make_location(session)
    seller = make_business(session, location)
    buyer = make_business(session, location, role=BusinessRole.BUYER)
    other = make_business(session, location)
    listing = make_listing(session, seller, location)
    with pytest.raises(IntegrityError):
        make_enquiry(session, listing, buyer, seller_business_id=other.business_id)


def test_cancelled_enquiry_needs_a_reason(session):
    location = make_location(session)
    seller = make_business(session, location)
    buyer = make_business(session, location, role=BusinessRole.BUYER)
    listing = make_listing(session, seller, location)
    with pytest.raises(IntegrityError):
        make_enquiry(session, listing, buyer, status=EnquiryStatus.CANCELLED)


def test_cancelled_enquiry_with_a_reason_is_allowed(session):
    location = make_location(session)
    seller = make_business(session, location)
    buyer = make_business(session, location, role=BusinessRole.BUYER)
    listing = make_listing(session, seller, location)
    enquiry = make_enquiry(
        session,
        listing,
        buyer,
        status=EnquiryStatus.CANCELLED,
        failure_reason=FailureReason.PRICE,
    )
    assert enquiry.failure_reason == FailureReason.PRICE


def test_buyer_has_one_open_enquiry_per_listing(session):
    location = make_location(session)
    seller = make_business(session, location)
    buyer = make_business(session, location, role=BusinessRole.BUYER)
    listing = make_listing(session, seller, location)
    make_enquiry(session, listing, buyer)
    with pytest.raises(IntegrityError):
        make_enquiry(session, listing, buyer)


def test_two_buyers_can_enquire_about_the_same_listing(session):
    location = make_location(session)
    seller = make_business(session, location)
    first = make_business(session, location, role=BusinessRole.BUYER)
    second = make_business(session, location, role=BusinessRole.BUYER)
    listing = make_listing(session, seller, location)
    make_enquiry(session, listing, first)
    other = make_enquiry(session, listing, second)
    assert other.enquiry_id is not None


def test_new_enquiry_starts_as_enquiry(session):
    enquiry = make_open_enquiry(session)
    assert enquiry.status == EnquiryStatus.ENQUIRY


def test_buyer_cannot_be_the_seller(session):
    location = make_location(session)
    seller = make_business(session, location)
    listing = make_listing(session, seller, location)
    with pytest.raises(IntegrityError):
        make_enquiry(session, listing, seller)


def test_failure_reason_only_belongs_to_a_failed_enquiry(session):
    location = make_location(session)
    seller = make_business(session, location)
    buyer = make_business(session, location, role=BusinessRole.BUYER)
    listing = make_listing(session, seller, location)
    with pytest.raises(IntegrityError):
        make_enquiry(session, listing, buyer, failure_reason=FailureReason.PRICE)


def test_buyer_can_enquire_again_after_the_first_is_completed(session):
    location = make_location(session)
    seller = make_business(session, location)
    buyer = make_business(session, location, role=BusinessRole.BUYER)
    listing = make_listing(session, seller, location)
    make_enquiry(session, listing, buyer, status=EnquiryStatus.COMPLETED)
    again = make_enquiry(session, listing, buyer)
    assert again.status == EnquiryStatus.ENQUIRY


def test_payment_amount_must_be_above_zero(session):
    enquiry = make_open_enquiry(session)
    with pytest.raises(IntegrityError):
        make_payment(session, enquiry, amount=Decimal("0"))


def test_new_payment_starts_pending_and_not_due(session):
    payment = make_payment(session, make_open_enquiry(session))
    assert payment.status == PaymentStatus.PENDING
    assert payment.payout_status == PayoutStatus.NOT_DUE


def test_payment_reference_must_be_unique(session):
    enquiry = make_open_enquiry(session)
    make_payment(
        session, enquiry, reference_id="ref-1", status=PaymentStatus.SUCCESSFUL
    )
    with pytest.raises(IntegrityError):
        make_payment(
            session, enquiry, reference_id="ref-1", status=PaymentStatus.FAILED
        )


def test_enquiry_has_only_one_pending_payment(session):
    enquiry = make_open_enquiry(session)
    make_payment(session, enquiry)
    with pytest.raises(IntegrityError):
        make_payment(session, enquiry)


def test_enquiry_has_only_one_successful_payment(session):
    enquiry = make_open_enquiry(session)
    make_payment(session, enquiry, status=PaymentStatus.SUCCESSFUL)
    with pytest.raises(IntegrityError):
        make_payment(session, enquiry, status=PaymentStatus.SUCCESSFUL)


def test_new_payment_is_allowed_after_a_failed_one(session):
    enquiry = make_open_enquiry(session)
    make_payment(session, enquiry, status=PaymentStatus.FAILED)
    retry = make_payment(session, enquiry)
    assert retry.status == PaymentStatus.PENDING


def test_new_notification_is_unread(session):
    user = make_user(session, role=UserRole.ADMIN)
    notification = make_notification(session, user)
    assert notification.read_at is None


def test_deleting_a_user_deletes_their_notifications(session):
    user = make_user(session, role=UserRole.ADMIN)
    make_notification(session, user)
    session.delete(user)
    session.flush()
    session.expire_all()
    count = session.scalar(select(func.count()).select_from(Notification))
    assert count == 0


def test_deleting_an_enquiry_keeps_the_notification_without_it(session):
    enquiry = make_open_enquiry(session)
    user = make_user(session, role=UserRole.ADMIN)
    notification = make_notification(session, user, enquiry_id=enquiry.enquiry_id)
    session.delete(enquiry)
    session.flush()
    session.expire_all()
    assert notification.enquiry_id is None


def test_price_guide_min_price_must_be_above_zero(session):
    with pytest.raises(IntegrityError):
        make_price_guide(session, min_price=Decimal("0"))


def test_price_guide_max_price_cannot_be_below_min_price(session):
    with pytest.raises(IntegrityError):
        make_price_guide(session, min_price=Decimal("60"), max_price=Decimal("30"))


def test_price_guide_allows_equal_min_and_max_price(session):
    guide = make_price_guide(session, min_price=Decimal("40"), max_price=Decimal("40"))
    assert guide.guide_id is not None
