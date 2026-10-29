import random
import uuid
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

from database import _session_factory
from models.business import (
    ApprovalStatus,
    Business,
    BusinessRole,
    BusinessType,
    SupplierKind,
)
from models.enquiry import Enquiry, EnquiryStatus
from models.listing import (
    Listing,
    ListingStatus,
    ListingType,
    SortingStatus,
    Stream,
    Unit,
)
from models.location import Location, OsmType
from models.user import User, UserRole

SessionLocal = _session_factory()
db = SessionLocal()

try:
    # 1. Location
    loc = Location(
        osm_type=OsmType.NODE,
        osm_id=random.randint(10000000, 99999999),
        name="Nairobi Central",
        display_name="Nairobi Central, Nairobi, Kenya",
        latitude=Decimal("-1.286389"),
        longitude=Decimal("36.817223"),
        district="Nairobi",
        province="Nairobi",
    )
    db.add(loc)
    db.flush()

    # 2. Seller Business
    seller_biz = Business(
        business_legal_name=f"Seller Ltd {uuid.uuid4().hex[:6]}",
        display_name="Organic Waste Processors",
        business_role=BusinessRole.SUPPLIER,
        business_type=BusinessType.BUSINESS,
        supplier_kind=SupplierKind.PRODUCER,
        location_id=loc.location_id,
        streams=["SAWDUST"],
        contact_email=f"seller_{uuid.uuid4().hex[:6]}@example.com",
        contact_phone="254708374149",
        registration_number=f"REG-{uuid.uuid4().hex[:6]}",
        approval_status=ApprovalStatus.APPROVED,
        payout_phone=None,
        payout_network=None,
    )

    # 3. Buyer Business
    buyer_biz = Business(
        business_legal_name=f"Buyer Ltd {uuid.uuid4().hex[:6]}",
        display_name="Eco Briquettes Ltd",
        business_role=BusinessRole.BUYER,
        business_type=BusinessType.BUSINESS,
        location_id=loc.location_id,
        streams=["SAWDUST"],
        contact_email=f"buyer_{uuid.uuid4().hex[:6]}@example.com",
        contact_phone="254708374149",
        registration_number=f"REG-{uuid.uuid4().hex[:6]}",
        approval_status=ApprovalStatus.APPROVED,
        payout_phone=None,
        payout_network=None,
    )
    db.add(seller_biz)
    db.add(buyer_biz)
    db.flush()

    # 4. Buyer User
    buyer_user = User(
        business_id=buyer_biz.business_id,
        first_name="Jane",
        last_name="Buyer",
        email=f"buyer_{uuid.uuid4().hex[:6]}@example.com",
        phone="254708374149",
        password_hash="dummyhash",
        user_role=UserRole.BUSINESS_USER,
    )
    db.add(buyer_user)
    db.flush()

    # 5. Listing
    listing = Listing(
        business_id=seller_biz.business_id,
        listing_type=ListingType.RAW_BYPRODUCT,
        stream=Stream.SAWDUST,
        material_or_product="Pine Wood Sawdust",
        specifications={"dryness": "85%"},
        photos=[],
        quantity=Decimal("100.000"),
        unit=Unit.KILOGRAM,
        location_id=loc.location_id,
        sorting_status=SortingStatus.SORTED,
        unit_price=Decimal("10.0000"),
        status=ListingStatus.PUBLISHED,
    )
    db.add(listing)
    db.flush()

    # 6. Agreed Enquiry
    enquiry = Enquiry(
        listing_id=listing.listing_id,
        buyer_business_id=buyer_biz.business_id,
        seller_business_id=seller_biz.business_id,
        status=EnquiryStatus.AGREED,
        quantity=Decimal("5.000"),
        unit=Unit.KILOGRAM,
        unit_price=Decimal("10.0000"),
        total_amount=Decimal("50.0000"),
    )
    db.add(enquiry)
    db.commit()

    print("\n" + "=" * 50)
    print("SUCCESS! Use this enquiry_id in Swagger:")
    print(enquiry.enquiry_id)
    print("=" * 50 + "\n")

except Exception as e:
    db.rollback()
    print("Error seeding:", e)
finally:
    db.close()
