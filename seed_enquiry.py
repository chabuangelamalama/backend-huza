import random
import sys
import uuid
from decimal import Decimal

from sqlalchemy import select

from database import SessionLocal
from models.business import (
    ApprovalStatus,
    Business,
    BusinessRole,
    BusinessType,
    PayoutNetwork,
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
from models.user import User

SELLER_PAYOUT_PHONE = "254708374149"


def main(buyer_email: str) -> None:
    db = SessionLocal()
    try:
        buyer_user = db.execute(
            select(User).where(User.email == buyer_email.strip().lower())
        ).scalar_one_or_none()
        if buyer_user is None or buyer_user.business_id is None:
            sys.exit(
                f"No user with a business found for {buyer_email}. Register first."
            )

        buyer_biz = db.get(Business, buyer_user.business_id)
        buyer_biz.approval_status = ApprovalStatus.APPROVED

        loc = Location(
            osm_type=OsmType.NODE,
            osm_id=random.randint(10000000, 99999999),
            name="Nairobi Central",
            display_name="Nairobi Central, Nairobi, Kenya",
            latitude=Decimal("-1.286389"),
            longitude=Decimal("36.817223"),
            sub_county="Starehe",
            county="Nairobi",
        )
        db.add(loc)
        db.flush()

        seller_biz = Business(
            business_legal_name=f"Seller Ltd {uuid.uuid4().hex[:6]}",
            display_name="Organic Waste Processors",
            business_role=BusinessRole.SUPPLIER,
            business_type=BusinessType.BUSINESS,
            supplier_kind=SupplierKind.PRODUCER,
            location_id=loc.location_id,
            streams=["SAWDUST"],
            contact_email=f"seller_{uuid.uuid4().hex[:6]}@example.com",
            contact_phone=SELLER_PAYOUT_PHONE,
            registration_number=f"REG-{uuid.uuid4().hex[:6]}",
            approval_status=ApprovalStatus.APPROVED,
            payout_phone=SELLER_PAYOUT_PHONE,
            payout_network=PayoutNetwork.MPESA,
        )
        db.add(seller_biz)
        db.flush()

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
        print(f"Buyer {buyer_email} approved. AGREED enquiry (KES 50):")
        print(enquiry.enquiry_id)
        print("=" * 50 + "\n")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: uv run python seed_enquiry.py <buyer-email>")
    main(sys.argv[1])
