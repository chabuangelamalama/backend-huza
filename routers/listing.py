from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from core.dependencies import get_current_user
from database import get_db
from models.listing import ListingType, Stream
from schemas.listing import ListingCreate, ListingRead, ListingUpdate
from services import listing_service

router = APIRouter(prefix="/listing", tags=["listing"])


@router.post("/", response_model=ListingRead, status_code=201)
def create_listing(
    data: ListingCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listing_service.create_listing(db, data, current_user)


@router.get(
    "/",
    response_model=list[ListingRead],
    dependencies=[Depends(get_current_user)],
)
def list_published(
    stream: Stream | None = None,
    listing_type: ListingType | None = None,
    location_id: UUID | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    return listing_service.list_published(db, stream, listing_type, location_id, search)


@router.get("/mine", response_model=list[ListingRead])
def list_my_listings(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listing_service.list_my_listings(db, current_user)


@router.get("/{listing_id}", response_model=ListingRead)
def get_listing(
    listing_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listing_service.get_listing(db, listing_id, current_user)


@router.patch("/{listing_id}", response_model=ListingRead)
def update_listing(
    listing_id: UUID,
    data: ListingUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listing_service.update_listing(db, listing_id, data, current_user)


@router.delete("/{listing_id}", response_model=ListingRead)
def close_listing(
    listing_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listing_service.close_listing(db, listing_id, current_user)


@router.post("/{listing_id}/photos", response_model=ListingRead, status_code=201)
def add_photo(
    listing_id: UUID,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    data = photo.file.read(listing_service.MAX_PHOTO_BYTES + 1)
    return listing_service.add_photo(db, listing_id, data, current_user)


@router.get("/{listing_id}/photos/{photo_id}")
def get_photo(
    listing_id: UUID,
    photo_id: UUID,
    db: Session = Depends(get_db),
):
    photo = listing_service.get_photo(db, listing_id, photo_id)
    return Response(
        content=photo.data,
        media_type=photo.content_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{listing_id}/photos/{photo_id}", response_model=ListingRead)
def remove_photo(
    listing_id: UUID,
    photo_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listing_service.remove_photo(db, listing_id, photo_id, current_user)
