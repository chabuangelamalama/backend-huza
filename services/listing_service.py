from datetime import datetime, timezone
from io import BytesIO
from uuid import UUID

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from models.business import ApprovalStatus, BusinessRole
from models.listing import ListingStatus, ListingType, Stream
from repositories.listing_repository import listing_repository
from schemas.listing import ListingCreate, ListingUpdate

MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTO_PIXELS = 25_000_000
MAX_PHOTO_SIZE = 1600
MAX_SPECIFICATIONS = 20
MAX_NAME_LENGTH = 150

ALLOWED_STATUS_CHANGES = {
    ListingStatus.DRAFT: {ListingStatus.PUBLISHED, ListingStatus.CLOSED},
    ListingStatus.PUBLISHED: {ListingStatus.PAUSED, ListingStatus.CLOSED},
    ListingStatus.PAUSED: {ListingStatus.PUBLISHED, ListingStatus.CLOSED},
    ListingStatus.EXPIRED: {ListingStatus.PUBLISHED, ListingStatus.CLOSED},
    ListingStatus.CLOSED: set(),
}


def _error(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def listing_type_for_role(role: BusinessRole) -> ListingType | None:
    if role == BusinessRole.SUPPLIER:
        return ListingType.RAW_BYPRODUCT
    if role == BusinessRole.PROCESSOR:
        return ListingType.FINISHED_PRODUCT
    return None


def can_change_status(current: ListingStatus, new: ListingStatus) -> bool:
    return new in ALLOWED_STATUS_CHANGES[current]


def detect_photo_format(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def clean_photo(data: bytes) -> tuple[bytes, int, int]:
    if not data:
        raise _error(400, "The photo is empty.")
    if len(data) > MAX_PHOTO_BYTES:
        raise _error(413, "A photo can be at most 5 MB.")
    if detect_photo_format(data) is None:
        raise _error(400, "Only JPEG, PNG and WEBP photos are allowed.")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > MAX_PHOTO_PIXELS:
                raise _error(400, "The photo is too large. Use a smaller image.")
            upright = ImageOps.exif_transpose(image)
            mode = "RGBA" if "A" in upright.getbands() else "RGB"
            clean = upright.convert(mode)
            clean.thumbnail((MAX_PHOTO_SIZE, MAX_PHOTO_SIZE))
            output = BytesIO()
            clean.save(output, format="WEBP", quality=80)
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
    ) as error:
        raise _error(400, "The photo is damaged or is not a real image.") from error
    return output.getvalue(), clean.width, clean.height


def _get_business(db, current_user):
    if current_user.business_id is None:
        raise _error(403, "Only business accounts can manage listings.")
    business = listing_repository.get_business(db, current_user.business_id)
    if business is None:
        raise _error(404, "Business not found.")
    return business


def _get_approved_business(db, current_user):
    business = _get_business(db, current_user)
    if business.approval_status != ApprovalStatus.APPROVED:
        raise _error(403, "Your business must be approved by HUZA to manage listings.")
    return business


def _get_own_listing(db, listing_id: UUID, business):
    listing = listing_repository.get(db, listing_id)
    if listing is None or listing.business_id != business.business_id:
        raise _error(404, "Listing not found.")
    return listing


def _check_not_closed(listing):
    if listing.status == ListingStatus.CLOSED:
        raise _error(400, "A closed listing cannot be changed.")


def _check_values(db, business, values: dict, creating: bool):
    if "material_or_product" in values:
        name = values["material_or_product"].strip()
        if not name:
            raise _error(400, "Add the material or product name.")
        if len(name) > MAX_NAME_LENGTH:
            raise _error(400, f"The name can be at most {MAX_NAME_LENGTH} characters.")
        values["material_or_product"] = name
    if "stream" in values and values["stream"] not in business.streams:
        raise _error(403, "Your business is not registered for this stream.")
    if "quantity" in values:
        if values["quantity"] < 0 or (creating and values["quantity"] == 0):
            raise _error(400, "Enter a quantity above 0.")
    if "unit_price" in values and values["unit_price"] <= 0:
        raise _error(400, "The price must be above 0.")
    if len(values.get("specifications", {})) > MAX_SPECIFICATIONS:
        raise _error(
            400, f"A listing can have at most {MAX_SPECIFICATIONS} specifications."
        )
    if (
        "location_id" in values
        and listing_repository.get_location(db, values["location_id"]) is None
    ):
        raise _error(400, "Location not found.")


def _check_status_change(listing, new_status: ListingStatus, quantity):
    if not can_change_status(listing.status, new_status):
        raise _error(
            400,
            f"A {listing.status.lower()} listing cannot be changed to {new_status.lower()}.",
        )
    if new_status == ListingStatus.PUBLISHED and quantity <= 0:
        raise _error(400, "Add a quantity above 0 before publishing.")


def create_listing(db, data: ListingCreate, current_user):
    business = _get_approved_business(db, current_user)
    listing_type = listing_type_for_role(business.business_role)
    if listing_type is None:
        raise _error(403, "Buyers cannot create listings.")
    values = data.model_dump()
    _check_values(db, business, values, creating=True)
    values["business_id"] = business.business_id
    values["listing_type"] = listing_type
    return listing_repository.create(db, values)


def get_listing(db, listing_id: UUID, current_user):
    listing = listing_repository.get(db, listing_id)
    if listing is None:
        raise _error(404, "Listing not found.")
    is_owner = listing.business_id == current_user.business_id
    if listing.status != ListingStatus.PUBLISHED and not is_owner:
        raise _error(404, "Listing not found.")
    return listing


def list_published(
    db,
    stream: Stream | None = None,
    listing_type: ListingType | None = None,
    location_id: UUID | None = None,
    search: str | None = None,
):
    return listing_repository.get_all(
        db,
        status=ListingStatus.PUBLISHED,
        stream=stream,
        listing_type=listing_type,
        location_id=location_id,
        search=search,
    )


def list_my_listings(db, current_user):
    business = _get_business(db, current_user)
    return listing_repository.get_by_business(db, business.business_id)


def update_listing(db, listing_id: UUID, data: ListingUpdate, current_user):
    business = _get_approved_business(db, current_user)
    listing = _get_own_listing(db, listing_id, business)
    _check_not_closed(listing)
    values = data.model_dump(exclude_unset=True, exclude_none=True)
    new_status = values.pop("status", listing.status)
    _check_values(db, business, values, creating=False)
    if new_status != listing.status:
        _check_status_change(
            listing, new_status, values.get("quantity", listing.quantity)
        )
        values["status"] = new_status
        if new_status == ListingStatus.PUBLISHED and listing.published_at is None:
            values["published_at"] = datetime.now(timezone.utc)
    return listing_repository.update(db, listing, values)


def close_listing(db, listing_id: UUID, current_user):
    business = _get_business(db, current_user)
    listing = _get_own_listing(db, listing_id, business)
    _check_status_change(listing, ListingStatus.CLOSED, listing.quantity)
    return listing_repository.update(db, listing, {"status": ListingStatus.CLOSED})


def add_photo(db, listing_id: UUID, data: bytes, current_user):
    business = _get_approved_business(db, current_user)
    listing = _get_own_listing(db, listing_id, business)
    _check_not_closed(listing)
    used = {photo.position for photo in listing.photos}
    free = [position for position in range(1, MAX_PHOTOS + 1) if position not in used]
    if not free:
        raise _error(400, f"A listing can have at most {MAX_PHOTOS} photos.")
    clean_data, width, height = clean_photo(data)
    photo = {
        "position": free[0],
        "content_type": "image/webp",
        "size_bytes": len(clean_data),
        "width": width,
        "height": height,
        "data": clean_data,
    }
    return listing_repository.add_photo(db, listing, photo)


def remove_photo(db, listing_id: UUID, photo_id: UUID, current_user):
    business = _get_approved_business(db, current_user)
    listing = _get_own_listing(db, listing_id, business)
    _check_not_closed(listing)
    photo = listing_repository.get_photo(db, listing.listing_id, photo_id)
    if photo is None:
        raise _error(404, "Photo not found.")
    return listing_repository.remove_photo(db, listing, photo)


def get_photo(db, listing_id: UUID, photo_id: UUID):
    photo = listing_repository.get_photo(db, listing_id, photo_id)
    if photo is None:
        raise _error(404, "Photo not found.")
    return photo
