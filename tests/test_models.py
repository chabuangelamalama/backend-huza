import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import inspect
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
from models.listing import ListingType, Stream, Unit
from models.location import OsmType
from models.notification import NotificationEvent
from models.user import UserRole


try:
    from tests.test_payments_api import PAYER
except ImportError:
    PAYER = "254712345678"

SECRET = "super-secret-callback-key"


def make_settings(**kwargs):
    """Dynamic configuration helper mock for dependency injection."""

    class Settings:
        def __init__(self, **opts):
            for k, v in opts.items():
                setattr(self, k, v)
            self.mpesa_callback_secret = SECRET

    return Settings(**kwargs)


def make_location(session, osm_id=1, osm_type=OsmType.NODE):
    location = Location(
        osm_type=osm_type,
        osm_id=osm_id,
        name="Karen",
        display_name="Karen, Nairobi, Kenya",
        latitude=Decimal("-1.320000"),
        longitude=Decimal("36.702000"),
        district="Nairobi",
        province="Nairobi County",
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
        business_legal_name="Nairobi Timber Works",
        business_role=role,
        business_type=business_type,
        location_id=location.location_id,
        streams=["SAWDUST"],
        contact_email="info@example.ke",
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
        email=f"{uuid.uuid4().hex}@example.ke",
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
        phone_number=PAYER,
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
        source="Nairobi market survey",
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
            email="diane@huza.ke",
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
            email="jean@example.ke",
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
        make_business(session, location, payout_phone=PAYER)


def test_payout_phone_with_a_network_is_allowed(session):
    location = make_location(session)
    business = make_business(
        session,
        location,
        payout_phone=PAYER,
        payout_network=PayoutNetwork.MPESA,
    )
    assert business.payout_network == PayoutNetwork.MPESA


def test_user_role_defaults_to_business_user(session):
    business = make_business(session, make_location(session))
    user = make_user(session, business, role=None)
    assert user.user_role == UserRole.BUSINESS_USER


def test_email_must_be_unique(session):
    location = make_location(session)
