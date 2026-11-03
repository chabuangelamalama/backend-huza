import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.exc import IntegrityError

import database
from core.dependencies import get_current_user
from models.business import ApprovalStatus, Business, BusinessRole, BusinessType
from models.listing import Listing, ListingStatus, ListingType, Stream, Unit
from models.location import Location, OsmType
from repositories.listing_repository import listing_repository as repository
from routers.listing import router
from schemas.listing import ListingCreate, ListingRead, ListingUpdate
from services import listing_service

BUSINESS_ID = uuid4()
OTHER_BUSINESS_ID = uuid4()
DB = object()
LISTING_ID = str(uuid4())
LOCATION_ID = str(uuid4())
STORED_PHOTO = {
    "position": 1,
    "content_type": "image/webp",
    "size_bytes": 3,
    "width": 10,
    "height": 10,
    "data": "YWJj",
}

SAMPLE = {
    "listing_id": LISTING_ID,
    "business_id": str(uuid4()),
    "listing_type": "RAW_BYPRODUCT",
    "stream": "SAWDUST",
    "material_or_product": "Pine sawdust, kiln-dried",
    "specifications": {"moisture": "8%"},
    "photos": [],
    "quantity": 12000,
    "unit": "KILOGRAM",
    "location_id": LOCATION_ID,
    "sorting_status": "SORTED",
    "unit_price": 40,
    "status": "DRAFT",
    "published_at": None,
    "created_at": "2026-10-27T10:00:00Z",
    "updated_at": "2026-10-27T10:00:00Z",
}

CREATE_BODY = {
    "stream": "SAWDUST",
    "material_or_product": "Pine sawdust, kiln-dried",
    "quantity": 12000,
    "unit": "KILOGRAM",
    "location_id": LOCATION_ID,
    "unit_price": 40,
}

FORM_BODY = {**CREATE_BODY, "specifications": json.dumps({"moisture": "8%"})}


def make_image(photo_format="PNG", mode="RGB", size=(10, 10), exif=None):
    output = BytesIO()
    options = {"exif": exif} if exif else {}
    Image.new(mode, size).save(output, format=photo_format, **options)
    return output.getvalue()


def open_image(data):
    return Image.open(BytesIO(data))


def raises_status(code, action):
    with pytest.raises(HTTPException) as error:
        action()
    assert error.value.status_code == code


def apply_values(db, listing, values):
    for key, value in values.items():
        setattr(listing, key, value)
    return listing


def make_user(business_id=BUSINESS_ID):
    return SimpleNamespace(business_id=business_id)


def make_business(role=BusinessRole.SUPPLIER, approval=ApprovalStatus.APPROVED):
    return SimpleNamespace(
        business_id=BUSINESS_ID,
        business_role=role,
        approval_status=approval,
        streams=["SAWDUST", "PLASTIC"],
    )


def make_listing(
    status=ListingStatus.DRAFT,
    business_id=BUSINESS_ID,
    published_at=None,
    quantity=Decimal("100"),
    photos=None,
):
    return SimpleNamespace(
        listing_id=uuid4(),
        business_id=business_id,
        status=status,
        published_at=published_at,
        quantity=quantity,
        photos=photos or [],
    )


def make_create(**changes):
    values = {
        "stream": Stream.SAWDUST,
        "material_or_product": "Pine sawdust, kiln-dried",
        "quantity": Decimal("12000"),
        "unit": Unit.KILOGRAM,
        "location_id": uuid4(),
        "unit_price": Decimal("40"),
    }
    values.update(changes)
    return ListingCreate(**values)


def create(data=None, photos=None):
    if photos is None:
        photos = [make_image()]
    values = (data or make_create()).model_dump(mode="json")
    values["specifications"] = json.dumps(values["specifications"])
    return listing_service.create_listing(DB, values, photos, make_user())


@pytest.fixture
def repo(monkeypatch):
    fake = MagicMock()
    fake.update.side_effect = apply_values
    fake.create.side_effect = lambda db, values: values
    monkeypatch.setattr(listing_service, "listing_repository", fake)
    return fake


@pytest.fixture
def own_listing(repo):
    repo.get_business.return_value = make_business()
    listing = make_listing()
    repo.get.return_value = listing
    return listing


@pytest.mark.parametrize(
    "role, expected",
    [
        (BusinessRole.SUPPLIER, ListingType.RAW_BYPRODUCT),
        (BusinessRole.PROCESSOR, ListingType.FINISHED_PRODUCT),
        (BusinessRole.BUYER, None),
    ],
)
def test_listing_type_for_role(role, expected):
    assert listing_service.listing_type_for_role(role) == expected


@pytest.mark.parametrize(
    "current, new, allowed",
    [
        (ListingStatus.DRAFT, ListingStatus.PUBLISHED, True),
        (ListingStatus.PUBLISHED, ListingStatus.PAUSED, True),
        (ListingStatus.PAUSED, ListingStatus.PUBLISHED, True),
        (ListingStatus.EXPIRED, ListingStatus.PUBLISHED, True),
        (ListingStatus.PUBLISHED, ListingStatus.CLOSED, True),
        (ListingStatus.CLOSED, ListingStatus.PUBLISHED, False),
        (ListingStatus.DRAFT, ListingStatus.PAUSED, False),
        (ListingStatus.PUBLISHED, ListingStatus.DRAFT, False),
    ],
)
def test_status_changes(current, new, allowed):
    assert listing_service.can_change_status(current, new) is allowed


def test_listing_status_as_text():
    assert str(ListingStatus.DRAFT) == "DRAFT"


def test_photo_read_hides_photo_data():
    read = ListingRead.model_validate({**SAMPLE, "photos": [STORED_PHOTO]})
    assert read.photos[0].position == 1
    assert "data" not in read.photos[0].model_dump()


@pytest.mark.parametrize(
    "data, expected",
    [
        (make_image("JPEG"), "JPEG"),
        (make_image("PNG"), "PNG"),
        (make_image("WEBP"), "WEBP"),
        (make_image("GIF"), None),
    ],
)
def test_detect_photo_format(data, expected):
    assert listing_service.detect_photo_format(data) == expected


def test_clean_photo_rejects_empty_file():
    raises_status(400, lambda: listing_service.clean_photo(b""))


def test_clean_photo_rejects_large_file(monkeypatch):
    monkeypatch.setattr(listing_service, "MAX_PHOTO_BYTES", 10)
    raises_status(413, lambda: listing_service.clean_photo(make_image()))


def test_clean_photo_rejects_other_formats():
    raises_status(400, lambda: listing_service.clean_photo(make_image("GIF")))


def test_clean_photo_rejects_fake_image():
    fake = b"\x89PNG\r\n\x1a\n" + b"this is not really an image"
    raises_status(400, lambda: listing_service.clean_photo(fake))


def test_clean_photo_rejects_huge_dimensions(monkeypatch):
    monkeypatch.setattr(listing_service, "MAX_PHOTO_PIXELS", 50)
    raises_status(400, lambda: listing_service.clean_photo(make_image()))


def test_clean_photo_saves_small_webp():
    data, width, height = listing_service.clean_photo(make_image(size=(2000, 1000)))
    assert open_image(data).format == "WEBP"
    assert (width, height) == (1600, 800)


def test_clean_photo_removes_metadata():
    exif = Image.Exif()
    exif[0x010F] = "Test Camera"
    original = make_image("JPEG", exif=exif.tobytes())
    assert len(open_image(original).getexif()) > 0
    data, _, _ = listing_service.clean_photo(original)
    assert len(open_image(data).getexif()) == 0


def test_clean_photo_turns_phone_photo_upright():
    exif = Image.Exif()
    exif[0x0112] = 6
    original = make_image("JPEG", size=(20, 10), exif=exif.tobytes())
    _, width, height = listing_service.clean_photo(original)
    assert (width, height) == (10, 20)


def test_clean_photo_keeps_transparency():
    data, _, _ = listing_service.clean_photo(make_image("PNG", mode="RGBA"))
    assert open_image(data).mode == "RGBA"


def test_clean_photo_converts_cmyk_jpeg():
    data, _, _ = listing_service.clean_photo(make_image("JPEG", mode="CMYK"))
    assert open_image(data).mode == "RGB"


def test_prepare_photos_numbers_positions():
    photos = listing_service.prepare_photos([make_image("PNG"), make_image("JPEG")])
    assert [photo["position"] for photo in photos] == [1, 2]
    assert all(photo["content_type"] == "image/webp" for photo in photos)
    for photo in photos:
        saved = base64.b64decode(photo["data"])
        assert photo["size_bytes"] == len(saved)
        assert open_image(saved).format == "WEBP"


def test_prepare_photos_refuses_more_than_five():
    raises_status(400, lambda: listing_service.prepare_photos([make_image()] * 6))


def test_user_without_business_cannot_manage_listings(repo):
    raises_status(403, lambda: listing_service.list_my_listings(DB, make_user(None)))


def test_missing_business_is_not_found(repo):
    repo.get_business.return_value = None
    raises_status(404, lambda: listing_service.list_my_listings(DB, make_user()))


def test_list_my_listings(repo):
    repo.get_business.return_value = make_business()
    repo.get_by_business.return_value = ["listing"]
    assert listing_service.list_my_listings(DB, make_user()) == ["listing"]
    repo.get_by_business.assert_called_once_with(DB, BUSINESS_ID)


def test_pending_business_cannot_create_listing(repo):
    repo.get_business.return_value = make_business(approval=ApprovalStatus.PENDING)
    raises_status(403, create)


def test_buyer_cannot_create_listing(repo):
    repo.get_business.return_value = make_business(role=BusinessRole.BUYER)
    raises_status(403, create)


def test_supplier_creates_listing_for_own_business(repo):
    repo.get_business.return_value = make_business()
    values = create(make_create(material_or_product="  Pine sawdust  "))
    assert values["material_or_product"] == "Pine sawdust"
    assert values["listing_type"] == ListingType.RAW_BYPRODUCT
    assert values["business_id"] == BUSINESS_ID
    assert len(values["photos"]) == 1
    assert "status" not in values


def test_create_with_photos_saves_them_together(repo):
    repo.get_business.return_value = make_business()
    values = create(photos=[make_image("PNG"), make_image("JPEG")])
    assert [photo["position"] for photo in values["photos"]] == [1, 2]
    repo.create.assert_called_once()


def test_bad_photo_saves_nothing(repo):
    repo.get_business.return_value = make_business()
    raises_status(400, lambda: create(photos=[make_image("PNG"), make_image("GIF")]))
    repo.create.assert_not_called()


def test_sixth_photo_saves_nothing(repo):
    repo.get_business.return_value = make_business()
    raises_status(400, lambda: create(photos=[make_image()] * 6))
    repo.create.assert_not_called()


def test_create_without_photos_saves_nothing(repo):
    repo.get_business.return_value = make_business()
    raises_status(400, lambda: create(photos=[]))
    repo.create.assert_not_called()


@pytest.mark.parametrize(
    "changes, code",
    [
        ({"material_or_product": "   "}, 400),
        ({"material_or_product": "x" * 151}, 400),
        ({"stream": Stream.GLASS}, 403),
        ({"quantity": Decimal("0")}, 400),
        ({"unit_price": Decimal("0")}, 400),
        ({"specifications": {str(number): "x" for number in range(21)}}, 400),
    ],
)
def test_create_rejects_bad_values(repo, changes, code):
    repo.get_business.return_value = make_business()
    raises_status(code, lambda: create(make_create(**changes)))


def test_create_rejects_unknown_location(repo):
    repo.get_business.return_value = make_business()
    repo.get_location.return_value = None
    raises_status(400, create)


@pytest.mark.parametrize(
    "data",
    [
        {**FORM_BODY, "business_id": str(uuid4())},
        {**FORM_BODY, "quantity": "lots"},
        {**FORM_BODY, "specifications": "not json"},
    ],
)
def test_create_refuses_bad_listing_data(repo, data):
    repo.get_business.return_value = make_business()
    with pytest.raises(RequestValidationError):
        listing_service.create_listing(DB, data, [make_image()], make_user())
    repo.create.assert_not_called()


def test_get_missing_listing(repo):
    repo.get.return_value = None
    raises_status(404, lambda: listing_service.get_listing(DB, uuid4(), make_user()))


def test_other_business_cannot_see_a_draft(repo):
    repo.get.return_value = make_listing(business_id=OTHER_BUSINESS_ID)
    raises_status(404, lambda: listing_service.get_listing(DB, uuid4(), make_user()))


def test_owner_can_see_own_draft(repo):
    listing = make_listing()
    repo.get.return_value = listing
    assert listing_service.get_listing(DB, listing.listing_id, make_user()) is listing


def test_anyone_can_see_a_published_listing(repo):
    listing = make_listing(
        status=ListingStatus.PUBLISHED, business_id=OTHER_BUSINESS_ID
    )
    repo.get.return_value = listing
    assert listing_service.get_listing(DB, listing.listing_id, make_user()) is listing


def test_list_published_only_asks_for_published(repo):
    repo.get_all.return_value = ["listing"]
    assert listing_service.list_published(DB, stream=Stream.PLASTIC) == ["listing"]
    repo.get_all.assert_called_once_with(
        DB,
        status=ListingStatus.PUBLISHED,
        stream=Stream.PLASTIC,
        listing_type=None,
        location_id=None,
        search=None,
    )


def test_update_missing_listing(repo):
    repo.get_business.return_value = make_business()
    repo.get.return_value = None
    raises_status(
        404,
        lambda: listing_service.update_listing(
            DB, uuid4(), ListingUpdate(unit_price=Decimal("45")), make_user()
        ),
    )


def test_update_another_business_listing(repo):
    repo.get_business.return_value = make_business()
    repo.get.return_value = make_listing(business_id=OTHER_BUSINESS_ID)
    raises_status(
        404,
        lambda: listing_service.update_listing(
            DB, uuid4(), ListingUpdate(unit_price=Decimal("45")), make_user()
        ),
    )


def test_update_closed_listing(own_listing):
    own_listing.status = ListingStatus.CLOSED
    raises_status(
        400,
        lambda: listing_service.update_listing(
            DB,
            own_listing.listing_id,
            ListingUpdate(unit_price=Decimal("45")),
            make_user(),
        ),
    )


def test_update_price(own_listing):
    result = listing_service.update_listing(
        DB,
        own_listing.listing_id,
        ListingUpdate(unit_price=Decimal("45")),
        make_user(),
    )
    assert result.unit_price == Decimal("45")
    assert result.status == ListingStatus.DRAFT


def test_update_rejects_negative_quantity(own_listing):
    raises_status(
        400,
        lambda: listing_service.update_listing(
            DB,
            own_listing.listing_id,
            ListingUpdate(quantity=Decimal("-1")),
            make_user(),
        ),
    )


def test_update_blocked_status_change(own_listing):
    raises_status(
        400,
        lambda: listing_service.update_listing(
            DB,
            own_listing.listing_id,
            ListingUpdate(status=ListingStatus.PAUSED),
            make_user(),
        ),
    )


def test_cannot_publish_without_quantity(own_listing):
    own_listing.quantity = Decimal("0")
    raises_status(
        400,
        lambda: listing_service.update_listing(
            DB,
            own_listing.listing_id,
            ListingUpdate(status=ListingStatus.PUBLISHED),
            make_user(),
        ),
    )


def test_publish_sets_published_at(own_listing):
    result = listing_service.update_listing(
        DB,
        own_listing.listing_id,
        ListingUpdate(status=ListingStatus.PUBLISHED),
        make_user(),
    )
    assert result.status == ListingStatus.PUBLISHED
    assert result.published_at is not None


def test_republish_keeps_first_published_at(own_listing):
    first_published = datetime(2026, 10, 1, tzinfo=timezone.utc)
    own_listing.status = ListingStatus.PAUSED
    own_listing.published_at = first_published
    result = listing_service.update_listing(
        DB,
        own_listing.listing_id,
        ListingUpdate(status=ListingStatus.PUBLISHED),
        make_user(),
    )
    assert result.published_at == first_published


def test_close_listing(own_listing):
    own_listing.status = ListingStatus.PUBLISHED
    result = listing_service.close_listing(DB, own_listing.listing_id, make_user())
    assert result.status == ListingStatus.CLOSED


def test_pending_business_can_still_close_listing(repo):
    repo.get_business.return_value = make_business(approval=ApprovalStatus.PENDING)
    listing = make_listing(status=ListingStatus.PUBLISHED)
    repo.get.return_value = listing
    result = listing_service.close_listing(DB, listing.listing_id, make_user())
    assert result.status == ListingStatus.CLOSED


def test_cannot_close_twice(own_listing):
    own_listing.status = ListingStatus.CLOSED
    raises_status(
        400,
        lambda: listing_service.close_listing(DB, own_listing.listing_id, make_user()),
    )


def test_get_photo_of_missing_listing(repo):
    repo.get.return_value = None
    raises_status(404, lambda: listing_service.get_photo(DB, uuid4(), 1))


def test_get_missing_photo(repo):
    repo.get.return_value = make_listing(photos=[STORED_PHOTO])
    raises_status(404, lambda: listing_service.get_photo(DB, uuid4(), 2))


def test_get_photo(repo):
    repo.get.return_value = make_listing(photos=[STORED_PHOTO])
    assert listing_service.get_photo(DB, uuid4(), 1) == (b"abc", "image/webp")


@pytest.fixture
def location(session):
    location = Location(
        osm_type=OsmType.NODE,
        osm_id=2001,
        name="Westlands",
        display_name="Westlands, Nairobi, Nairobi County, Kenya",
        latitude=Decimal("-1.267500"),
        longitude=Decimal("36.810800"),
        sub_county="Westlands",
        county="Nairobi",
    )
    session.add(location)
    session.flush()
    return location


def add_business(session, location, name, role):
    business = Business(
        business_legal_name=name,
        business_role=role,
        business_type=BusinessType.BUSINESS,
        location_id=location.location_id,
        streams=["SAWDUST", "PLASTIC"],
        contact_email=f"{uuid4().hex[:8]}@example.rw",
        approval_status=ApprovalStatus.APPROVED,
    )
    session.add(business)
    session.flush()
    return business


@pytest.fixture
def supplier(session, location):
    return add_business(session, location, "Kigali Timber Works", BusinessRole.SUPPLIER)


@pytest.fixture
def processor(session, location):
    return add_business(
        session, location, "GreenBoard Rwanda Ltd", BusinessRole.PROCESSOR
    )


def listing_values(business, location, **changes):
    values = {
        "business_id": business.business_id,
        "listing_type": ListingType.RAW_BYPRODUCT,
        "stream": Stream.SAWDUST,
        "material_or_product": "Pine sawdust, kiln-dried",
        "specifications": {"moisture": "8%"},
        "quantity": Decimal("12000"),
        "unit": Unit.KILOGRAM,
        "location_id": location.location_id,
        "unit_price": Decimal("40"),
    }
    values.update(changes)
    return values


def photo_values(position=1):
    return {**STORED_PHOTO, "position": position}


@pytest.fixture
def listing(session, supplier, location):
    return repository.create(session, listing_values(supplier, location))


def test_repository_new_listing_starts_as_draft(session, listing):
    assert listing.listing_id is not None
    assert listing.status == ListingStatus.DRAFT
    assert listing.photos == []
    assert session.get(Listing, listing.listing_id) is listing


def test_repository_saves_photos_with_listing(session, supplier, location):
    photos = [photo_values(1), photo_values(2)]
    listing = repository.create(
        session, listing_values(supplier, location, photos=photos)
    )
    session.expire_all()
    saved = session.get(Listing, listing.listing_id)
    assert [photo["position"] for photo in saved.photos] == [1, 2]
    assert saved.photos[0]["data"] == "YWJj"


def test_repository_database_blocks_sixth_photo(session, supplier, location):
    photos = [photo_values(number) for number in range(1, 7)]
    with pytest.raises(IntegrityError):
        repository.create(session, listing_values(supplier, location, photos=photos))


def test_repository_database_rejects_zero_price(session, supplier, location):
    with pytest.raises(IntegrityError):
        repository.create(
            session, listing_values(supplier, location, unit_price=Decimal("0"))
        )


def test_repository_get(session, listing):
    assert repository.get(session, listing.listing_id) is listing
    assert repository.get(session, uuid4()) is None


def test_repository_get_business_and_location(session, supplier, location):
    assert repository.get_business(session, supplier.business_id) is supplier
    assert repository.get_business(session, uuid4()) is None
    assert repository.get_location(session, location.location_id) is location
    assert repository.get_location(session, uuid4()) is None


def test_repository_get_all_filters(session, supplier, processor, location):
    sawdust = repository.create(
        session, listing_values(supplier, location, status=ListingStatus.PUBLISHED)
    )
    plastic = repository.create(
        session,
        listing_values(
            processor,
            location,
            listing_type=ListingType.FINISHED_PRODUCT,
            stream=Stream.PLASTIC,
            material_or_product="Recycled PET pellets",
        ),
    )
    assert set(repository.get_all(session)) == {sawdust, plastic}
    assert repository.get_all(session, status=ListingStatus.PUBLISHED) == [sawdust]
    assert repository.get_all(session, stream=Stream.PLASTIC) == [plastic]
    assert repository.get_all(session, listing_type=ListingType.FINISHED_PRODUCT) == [
        plastic
    ]
    assert set(repository.get_all(session, location_id=location.location_id)) == {
        sawdust,
        plastic,
    }
    assert repository.get_all(session, search="PINE") == [sawdust]
    assert repository.get_all(session, search="glass") == []


def test_repository_get_by_business(session, supplier, processor, location):
    own = repository.create(session, listing_values(supplier, location))
    repository.create(
        session,
        listing_values(processor, location, listing_type=ListingType.FINISHED_PRODUCT),
    )
    assert repository.get_by_business(session, supplier.business_id) == [own]


def test_repository_update(session, listing):
    repository.update(session, listing, {"unit_price": Decimal("45")})
    session.expire_all()
    assert session.get(Listing, listing.listing_id).unit_price == Decimal("45")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[database.get_db] = lambda: None
    app.dependency_overrides[get_current_user] = make_user
    return TestClient(app)


def test_router_create_listing_with_photos(client, monkeypatch):
    received = {}

    def fake(db, data, photos, user):
        received["name"] = data["material_or_product"]
        received["photos"] = photos
        return SAMPLE

    monkeypatch.setattr(listing_service, "create_listing", fake)
    first, second = make_image("PNG"), make_image("JPEG")
    response = client.post(
        "/listing/",
        data=FORM_BODY,
        files=[
            ("photos", ("one.png", first, "image/png")),
            ("photos", ("two.jpg", second, "image/jpeg")),
        ],
    )
    assert response.status_code == 201
    assert response.json()["status"] == "DRAFT"
    assert received == {"name": "Pine sawdust, kiln-dried", "photos": [first, second]}


def test_router_create_listing_without_photos(client, monkeypatch):
    received = {}

    def fake(db, data, photos, user):
        received["photos"] = photos
        return SAMPLE

    monkeypatch.setattr(listing_service, "create_listing", fake)
    response = client.post("/listing/", data=FORM_BODY)
    assert response.status_code == 201
    assert received == {"photos": []}


def test_router_needs_listing_data(client):
    assert client.post("/listing/").status_code == 422


def test_router_list_published(client, monkeypatch):
    calls = {}

    def fake(db, stream, listing_type, location_id, search):
        calls.update(stream=stream, search=search)
        return [SAMPLE]

    monkeypatch.setattr(listing_service, "list_published", fake)
    response = client.get("/listing/", params={"stream": "PLASTIC", "search": "pet"})
    assert response.status_code == 200
    assert calls == {"stream": Stream.PLASTIC, "search": "pet"}


def test_router_list_my_listings(client, monkeypatch):
    monkeypatch.setattr(listing_service, "list_my_listings", lambda db, user: [SAMPLE])
    response = client.get("/listing/mine")
    assert response.status_code == 200
    assert response.json()[0]["listing_id"] == LISTING_ID


def test_router_get_listing_hides_photo_data(client, monkeypatch):
    monkeypatch.setattr(
        listing_service,
        "get_listing",
        lambda db, listing_id, user: {**SAMPLE, "photos": [STORED_PHOTO]},
    )
    response = client.get(f"/listing/{LISTING_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["photos"] == [
        {
            "position": 1,
            "width": 10,
            "height": 10,
            "size_bytes": 3,
            "url": f"/listing/{body['listing_id']}/photos/1",
        }
    ]


def test_router_update_listing(client, monkeypatch):
    monkeypatch.setattr(
        listing_service,
        "update_listing",
        lambda db, listing_id, data, user: {**SAMPLE, "status": data.status},
    )
    response = client.patch(f"/listing/{LISTING_ID}", json={"status": "PUBLISHED"})
    assert response.status_code == 200
    assert response.json()["status"] == "PUBLISHED"


def test_router_close_listing(client, monkeypatch):
    monkeypatch.setattr(
        listing_service,
        "close_listing",
        lambda db, listing_id, user: {**SAMPLE, "status": "CLOSED"},
    )
    response = client.delete(f"/listing/{LISTING_ID}")
    assert response.status_code == 200
    assert response.json()["status"] == "CLOSED"


def test_router_get_photo_sends_image(client, monkeypatch):
    monkeypatch.setattr(
        listing_service,
        "get_photo",
        lambda db, listing_id, position: (b"abc", "image/webp"),
    )
    response = client.get(f"/listing/{LISTING_ID}/photos/1")
    assert response.status_code == 200
    assert response.content == b"abc"
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_get_current_user_is_not_ready_yet():
    app = FastAPI()

    @app.get("/")
    def protected(user=Depends(get_current_user)):
        return {"user": user}

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 401


def test_get_db_yields_a_session_and_closes_it(monkeypatch):
    from unittest.mock import MagicMock

    import database

    session_factory = MagicMock()
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    generator = database.get_db()
    assert next(generator) is session_factory.return_value.__enter__.return_value
    generator.close()
    session_factory.return_value.__exit__.assert_called_once()
