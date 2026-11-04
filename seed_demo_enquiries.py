"""Create several real, ready-to-pay enquiries for a payment demo.

Each enquiry gets its own seller, listing and amount, is already accepted by
the seller (status AGREED), and the seller has an M-Pesa payout number, so the
buyer can pay it straight away.

It also writes the mobile app's sample enquiry list with the real IDs, so the
enquiries show up in the app with a working Pay button.

Usage (from the backend folder, with DATABASE_URL pointing at your database):

    uv run --no-sync python seed_demo_enquiries.py <buyer-email> [path-to-mock_enquiries.dart]

Example:

    uv run --no-sync python seed_demo_enquiries.py chabuangelam@gmail.com \
        ~/athena-mobile/huza/lib/features/enquiry/data/mock_enquiries.dart
"""

import random
import sys
import uuid
from decimal import Decimal
from pathlib import Path

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

# seller name, product, stream, quantity (kg), price per kg (KES), place
DEMO_ENQUIRIES = [
    ("Kiambu Sawmills Ltd", "Pine sawdust, kiln-dried", Stream.SAWDUST, 5, 10, "Kiambu"),
    ("Nakuru Plastics Recyclers", "Clean PET flakes", Stream.PLASTIC, 4, 25, "Nakuru"),
    ("Thika Garment Offcuts", "Cotton offcuts, sorted", Stream.GARMENT_OFFCUTS, 10, 3, "Thika"),
    ("Mombasa Glass Collectors", "Crushed clear glass", Stream.GLASS, 2, 5, "Mombasa"),
    ("Eldoret Timber Works", "Hardwood shavings", Stream.SAWDUST, 1, 1, "Eldoret"),
]


def _location(place: str) -> Location:
    return Location(
        osm_type=OsmType.NODE,
        osm_id=random.randint(10000000, 99999999),
        name=f"{place} Town",
        display_name=f"{place}, Kenya",
        latitude=Decimal("-1.286389"),
        longitude=Decimal("36.817223"),
        sub_county=place,
        county=place,
    )


def create_demo_enquiries(buyer_email: str) -> list[dict]:
    db = SessionLocal()
    created = []
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

        for seller_name, product, stream, qty, price, place in DEMO_ENQUIRIES:
            loc = _location(place)
            db.add(loc)
            db.flush()

            seller = Business(
                business_legal_name=f"{seller_name} {uuid.uuid4().hex[:4]}",
                display_name=seller_name,
                business_role=BusinessRole.SUPPLIER,
                business_type=BusinessType.BUSINESS,
                supplier_kind=SupplierKind.PRODUCER,
                location_id=loc.location_id,
                streams=[stream.value],
                contact_email=f"seller_{uuid.uuid4().hex[:6]}@example.com",
                contact_phone=SELLER_PAYOUT_PHONE,
                registration_number=f"REG-{uuid.uuid4().hex[:6]}",
                approval_status=ApprovalStatus.APPROVED,
                payout_phone=SELLER_PAYOUT_PHONE,
                payout_network=PayoutNetwork.MPESA,
            )
            db.add(seller)
            db.flush()

            listing = Listing(
                business_id=seller.business_id,
                listing_type=ListingType.RAW_BYPRODUCT,
                stream=stream,
                material_or_product=product,
                specifications={},
                photos=[],
                quantity=Decimal("100.000"),
                unit=Unit.KILOGRAM,
                location_id=loc.location_id,
                sorting_status=SortingStatus.SORTED,
                unit_price=Decimal(price),
                status=ListingStatus.PUBLISHED,
            )
            db.add(listing)
            db.flush()

            enquiry = Enquiry(
                listing_id=listing.listing_id,
                buyer_business_id=buyer_biz.business_id,
                seller_business_id=seller.business_id,
                status=EnquiryStatus.AGREED,
                quantity=Decimal(qty),
                unit=Unit.KILOGRAM,
                unit_price=Decimal(price),
                total_amount=Decimal(qty * price),
            )
            db.add(enquiry)
            db.flush()

            created.append(
                {
                    "id": str(enquiry.enquiry_id),
                    "seller": seller_name,
                    "product": product,
                    "qty": qty,
                    "price": price,
                    "place": place,
                }
            )

        db.commit()
        return created
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _dart(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def write_mock_file(path: Path, rows: list[dict]) -> None:
    items = []
    for r in rows:
        items.append(
            "  Enquiry(\n"
            f"    id: '{r['id']}',\n"
            f"    sellerName: '{_dart(r['seller'])}',\n"
            f"    product: '{_dart(r['product'])}',\n"
            f"    quantityKg: {r['qty']},\n"
            f"    pricePerKg: {r['price']},\n"
            "    status: EnquiryStatus.accepted,\n"
            "    phone: '+254 708 374 149',\n"
            f"    pickupDetails: '{_dart(r['place'])} yard, Monday to Saturday, 8:00 to 17:00',\n"
            "  ),\n"
        )
    path.write_text(
        "import '../models/enquiry.dart';\n\n"
        "// DEMO DATA: real enquiry IDs from seed_demo_enquiries.py.\n"
        "// Restore before committing:\n"
        "//   git checkout -- lib/features/enquiry/data/mock_enquiries.dart\n"
        "const mockEnquiries = [\n" + "".join(items) + "];\n"
    )


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(
            "Usage: uv run --no-sync python seed_demo_enquiries.py "
            "<buyer-email> [path-to-mock_enquiries.dart]"
        )

    rows = create_demo_enquiries(sys.argv[1])

    print("\n" + "=" * 64)
    print(f"Created {len(rows)} ready-to-pay enquiries for {sys.argv[1]}:\n")
    for r in rows:
        total = r["qty"] * r["price"]
        print(f"  KES {total:>4}  {r['seller']:<28} {r['id']}")
    print("=" * 64)

    if len(sys.argv) == 3:
        target = Path(sys.argv[2]).expanduser()
        if not target.exists():
            sys.exit(f"\nCould not find {target}. Check the path and try again.")
        write_mock_file(target, rows)
        print(f"\nUpdated the app's enquiry list: {target}")
        print("Restart the app (Ctrl + C, then flutter run) to see them.\n")
