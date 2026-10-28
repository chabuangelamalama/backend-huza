from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.exc import IntegrityError

import database
from core.dependencies import get_current_user
from models.business import ApprovalStatus, Business, BusinessRole, BusinessType
from models.listing import Listing, ListingStatus, ListingType, Stream, Unit
from models.listing_photo import ListingPhoto
from models.location import Location, OsmType
from repositories.listing_repository import listing_repository as repository
from routers.listing import router
from schemas.listing import ListingCreate, ListingRead, ListingUpdate
from services import listing_service
from pydantic import ValidationError

BUSINESS_ID = uuid4()
OTHER_BUSINESS_ID = uuid4()
DB = object()
LISTING_ID = str(uuid4())
LOCATION_ID = str(uuid4())
PHOTO_ID = str(uuid4())

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
    positions=(),
):
    return SimpleNamespace(
        listing_id=uuid4(),
        business_id=business_id,
        status=status,
        published_at=published_at,
        quantity=quantity,
        photos=[SimpleNamespace(position=position) for position in positions],
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


@pytest.fixture
def repo(monkeypatch):
    fake = MagicMock()
    fake.update.side_effect = apply_values
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


def test_photo_read_has_url():
    photo = {
        "photo_id": PHOTO_ID,
        "listing_id": LISTING_ID,
        "position": 1,
        "width": 10,
        "height": 10,
        "size_bytes": 50,
    }
    read = ListingRead.model_validate({**SAMPLE, "photos": [photo]})
    assert read.photos[0].url == f"/listing/{LISTING_ID}/photos/{PHOTO_ID}"


@pytest.mark.parametrize(
    "changes",
    [
        {"material_or_product": "<script>alert(1)</script>"},
        {"specifications": {"<grade>": "A"}},
        {"specifications": {"grade": "A > B"}},
    ],
)
def test_create_refuses_angle_brackets(changes):
    with pytest.raises(ValidationError):
        make_create(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"material_or_product": "<b>Pine</b>"},
        {"specifications": {"grade": "<A>"}},
    ],
)
def test_update_refuses_angle_brackets(changes):
    with pytest.raises(ValidationError):
        ListingUpdate(**changes)


def test_update_without_text_is_allowed():
    update = ListingUpdate(unit_price=Decimal("45"))
    assert update.material_or_product is None
    assert update.specifications is None


def test_router_refuses_angle_brackets(client):
    response = client.post(
        "/listing/", json={**CREATE_BODY, "material_or_product": "<b>Pine</b>"}
    )
    assert response.status_code == 422


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
    assert open_image(data).size == (1600, 800)


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
    raises_status(
        403, lambda: listing_service.create_listing(DB, make_create(), make_user())
    )


def test_buyer_cannot_create_listing(repo):
    repo.get_business.return_value = make_business(role=BusinessRole.BUYER)
    raises_status(
        403, lambda: listing_service.create_listing(DB, make_create(), make_user())
    )


def test_supplier_creates_listing_for_own_business(repo):
    repo.get_business.return_value = make_business()
    repo.create.side_effect = lambda db, values: values
    values = listing_service.create_listing(
        DB, make_create(material_or_product="  Pine sawdust  "), make_user()
    )
    assert values["material_or_product"] == "Pine sawdust"
    assert values["listing_type"] == ListingType.RAW_BYPRODUCT
    assert values["business_id"] == BUSINESS_ID
    assert "status" not in values


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
    raises_status(
        code,
        lambda: listing_service.create_listing(DB, make_create(**changes), make_user()),
    )


def test_create_rejects_unknown_location(repo):
    repo.get_business.return_value = make_business()
    repo.get_location.return_value = None
    raises_status(
        400, lambda: listing_service.create_listing(DB, make_create(), make_user())
    )


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
        DB, own_listing.listing_id, ListingUpdate(unit_price=Decimal("45")), make_user()
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


def test_cannot_add_photo_to_closed_listing(own_listing):
    own_listing.status = ListingStatus.CLOSED
    raises_status(
        400,
        lambda: listing_service.add_photo(
            DB, own_listing.listing_id, make_image(), make_user()
        ),
    )


def test_cannot_add_more_than_five_photos(own_listing):
    own_listing.photos = [SimpleNamespace(position=number) for number in range(1, 6)]
    raises_status(
        400,
        lambda: listing_service.add_photo(
            DB, own_listing.listing_id, make_image(), make_user()
        ),
    )


def test_add_photo_uses_first_free_position(own_listing, repo):
    own_listing.photos = [SimpleNamespace(position=1), SimpleNamespace(position=3)]
    repo.add_photo.side_effect = lambda db, listing, photo: photo
    photo = listing_service.add_photo(
        DB, own_listing.listing_id, make_image("PNG"), make_user()
    )
    assert photo["position"] == 2
    assert photo["content_type"] == "image/webp"
    assert photo["size_bytes"] == len(photo["data"])
    assert (photo["width"], photo["height"]) == (10, 10)


def test_remove_missing_photo(own_listing, repo):
    repo.get_photo.return_value = None
    raises_status(
        404,
        lambda: listing_service.remove_photo(
            DB, own_listing.listing_id, uuid4(), make_user()
        ),
    )


def test_remove_photo(own_listing, repo):
    photo = SimpleNamespace(photo_id=uuid4())
    repo.get_photo.return_value = photo
    repo.remove_photo.return_value = own_listing
    result = listing_service.remove_photo(
        DB, own_listing.listing_id, photo.photo_id, make_user()
    )
    assert result is own_listing
    repo.remove_photo.assert_called_once_with(DB, own_listing, photo)


def test_cannot_remove_photo_from_closed_listing(own_listing):
    own_listing.status = ListingStatus.CLOSED
    raises_status(
        400,
        lambda: listing_service.remove_photo(
            DB, own_listing.listing_id, uuid4(), make_user()
        ),
    )


def test_get_missing_photo(repo):
    repo.get_photo.return_value = None
    raises_status(404, lambda: listing_service.get_photo(DB, uuid4(), uuid4()))


def test_get_photo(repo):
    photo = SimpleNamespace(data=b"abc")
    repo.get_photo.return_value = photo
    assert listing_service.get_photo(DB, uuid4(), uuid4()) is photo


@pytest.fixture
def location(session):
    location = Location(
        osm_type=OsmType.NODE,
        osm_id=2001,
        name="Remera",
        display_name="Remera, Gasabo, Kigali, Rwanda",
        latitude=Decimal("-1.951100"),
        longitude=Decimal("30.112600"),
        district="Gasabo",
        province="City of Kigali",
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


@pytest.fixture
def listing(session, supplier, location):
    return repository.create(session, listing_values(supplier, location))


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
    return {
        "position": position,
        "content_type": "image/webp",
        "size_bytes": 3,
        "width": 10,
        "height": 10,
        "data": b"abc",
    }


def test_repository_new_listing_starts_as_draft(session, listing):
    assert listing.listing_id is not None
    assert listing.status == ListingStatus.DRAFT
    assert listing.photos == []
    assert session.get(Listing, listing.listing_id) is listing


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


def test_repository_add_and_get_photo(session, listing):
    result = repository.add_photo(session, listing, photo_values())
    assert len(result.photos) == 1
    photo_id = result.photos[0].photo_id
    session.expire_all()
    photo = repository.get_photo(session, listing.listing_id, photo_id)
    assert photo.data == b"abc"
    assert photo.position == 1


def test_repository_photos_come_in_order(session, listing):
    repository.add_photo(session, listing, photo_values(position=3))
    result = repository.add_photo(session, listing, photo_values(position=1))
    assert [photo.position for photo in result.photos] == [1, 3]


def test_repository_get_photo_of_other_listing_is_none(session, listing):
    result = repository.add_photo(session, listing, photo_values())
    photo_id = result.photos[0].photo_id
    assert repository.get_photo(session, uuid4(), photo_id) is None


def test_repository_database_blocks_sixth_photo(session, listing):
    with pytest.raises(IntegrityError):
        repository.add_photo(session, listing, photo_values(position=6))


def test_repository_database_blocks_same_position(session, listing):
    repository.add_photo(session, listing, photo_values(position=1))
    with pytest.raises(IntegrityError):
        repository.add_photo(session, listing, photo_values(position=1))


def test_repository_remove_photo(session, listing):
    result = repository.add_photo(session, listing, photo_values())
    photo = repository.get_photo(session, listing.listing_id, result.photos[0].photo_id)
    result = repository.remove_photo(session, listing, photo)
    assert result.photos == []
    assert session.get(ListingPhoto, photo.photo_id) is None


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[database.get_db] = lambda: None
    app.dependency_overrides[get_current_user] = make_user
    return TestClient(app)


def test_router_create_listing(client, monkeypatch):
    monkeypatch.setattr(
        listing_service, "create_listing", lambda db, data, user: SAMPLE
    )
    response = client.post("/listing/", json=CREATE_BODY)
    assert response.status_code == 201
    assert response.json()["listing_id"] == LISTING_ID
    assert response.json()["status"] == "DRAFT"


def test_router_rejects_business_id_in_body(client):
    response = client.post(
        "/listing/", json={**CREATE_BODY, "business_id": str(uuid4())}
    )
    assert response.status_code == 422


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


def test_router_get_listing(client, monkeypatch):
    monkeypatch.setattr(
        listing_service, "get_listing", lambda db, listing_id, user: SAMPLE
    )
    assert client.get(f"/listing/{LISTING_ID}").status_code == 200


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


def test_router_add_photo(client, monkeypatch):
    received = {}

    def fake(db, listing_id, data, user):
        received["data"] = data
        return SAMPLE

    monkeypatch.setattr(listing_service, "add_photo", fake)
    image = make_image()
    response = client.post(
        f"/listing/{LISTING_ID}/photos",
        files={"photo": ("photo.png", image, "image/png")},
    )
    assert response.status_code == 201
    assert received["data"] == image


def test_router_get_photo_sends_image(client, monkeypatch):
    monkeypatch.setattr(
        listing_service,
        "get_photo",
        lambda db, listing_id, photo_id: SimpleNamespace(
            data=b"abc", content_type="image/webp"
        ),
    )
    response = client.get(f"/listing/{LISTING_ID}/photos/{PHOTO_ID}")
    assert response.status_code == 200
    assert response.content == b"abc"
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_router_remove_photo(client, monkeypatch):
    received = {}

    def fake(db, listing_id, photo_id, user):
        received["photo_id"] = str(photo_id)
        return SAMPLE

    monkeypatch.setattr(listing_service, "remove_photo", fake)
    response = client.delete(f"/listing/{LISTING_ID}/photos/{PHOTO_ID}")
    assert response.status_code == 200
    assert received["photo_id"] == PHOTO_ID


def test_get_db_without_database_url(monkeypatch):
    monkeypatch.setattr(database, "SessionLocal", None)
    raises_status(503, lambda: next(database.get_db()))


def test_get_db_opens_and_closes_session(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    generator = database.get_db()
    assert next(generator) is session
    generator.close()
    session.close.assert_called_once()


def test_get_current_user_is_not_ready_yet():
    raises_status(401, get_current_user)
