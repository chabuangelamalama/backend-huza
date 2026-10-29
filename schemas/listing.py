from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from models.listing import ListingStatus, ListingType, SortingStatus, Stream, Unit


class ListingPhotoRead(BaseModel):
    position: int
    width: int
    height: int
    size_bytes: int


class ListingPhotoLink(ListingPhotoRead):
    url: str = ""


class ListingBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: Stream
    material_or_product: str
    specifications: dict[str, str] = {}
    quantity: Decimal
    unit: Unit
    location_id: UUID
    sorting_status: SortingStatus | None = None
    unit_price: Decimal


class ListingCreate(ListingBase):
    pass


class ListingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: Stream | None = None
    material_or_product: str | None = None
    specifications: dict[str, str] | None = None
    quantity: Decimal | None = None
    unit: Unit | None = None
    location_id: UUID | None = None
    sorting_status: SortingStatus | None = None
    unit_price: Decimal | None = None
    status: ListingStatus | None = None


class ListingRead(ListingBase):
    model_config = ConfigDict(from_attributes=True)

    listing_id: UUID
    business_id: UUID
    listing_type: ListingType
    quantity: float
    unit_price: float
    photos: list[ListingPhotoLink] = []
    status: ListingStatus = ListingStatus.DRAFT
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def add_photo_urls(self):
        for photo in self.photos:
            photo.url = f"/listing/{self.listing_id}/photos/{photo.position}"
        return self
