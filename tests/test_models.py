from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from models import Business, Enquiry, Listing, Location, User
from models.enums import (
    BusinessRole,
    BusinessType,
    EnquiryStatus,
    ListingType,
    OsmType,
    Stream,
    Unit,
    UserRole,
)


def make_location(session, osm_id=1):
    location = Location(
        osm_type=OsmType.NODE,
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
):
    business = Business(
        business_legal_name="Kigali Timber Works",
        business_role=role,
        business_type=business_type,
        location_id=location.location_id,
        streams=["SAWDUST"],
        contact_email="info@example.rw",
    )
    session.add(business)
    session.flush()
    return business


def make_listing(session, business, location):
    listing = Listing(
        business_id=business.business_id,
        listing_type=ListingType.RAW_BYPRODUCT,
        stream=Stream.SAWDUST,
        material_or_product="Pine sawdust",
        quantity=Decimal("1000"),
        unit=Unit.KILOGRAM,
        unit_price=Decimal("50"),
        location_id=location.location_id,
    )
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


def test_all_nine_tables_exist(engine):
    names = set(inspect(engine).get_table_names())
    assert {
        "users",
        "businesses",
        "locations",
        "listings",
        "price_guides",
        "enquiries",
        "messages",
        "payments",
        "notifications",
    } <= names


def test_same_osm_place_is_saved_once(session):
    make_location(session, osm_id=10)
    with pytest.raises(IntegrityError):
        make_location(session, osm_id=10)


def test_new_business_starts_pending(session):
    business = make_business(session, make_location(session))
    assert business.approval_status.value == "PENDING"


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


def test_consumer_must_be_a_buyer(session):
    location = make_location(session)
    with pytest.raises(IntegrityError):
        make_business(
            session,
            location,
            role=BusinessRole.SUPPLIER,
            business_type=BusinessType.CONSUMER,
        )


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


def test_buyer_has_one_open_enquiry_per_listing(session):
    location = make_location(session)
    seller = make_business(session, location)
    buyer = make_business(session, location, role=BusinessRole.BUYER)
    listing = make_listing(session, seller, location)
    make_enquiry(session, listing, buyer)
    with pytest.raises(IntegrityError):
        make_enquiry(session, listing, buyer)
