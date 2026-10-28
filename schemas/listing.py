from datetime import datetime
from decimal import Decimal
from uuid import UUID
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    computed_field,
)

from models.listing import ListingStatus, ListingType, SortingStatus, Stream, Unit

SafeText = Annotated[str, StringConstraints(pattern=r"^[^<>]*$")]


class ListingPhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    photo_id: UUID
    listing_id: UUID
    position: int
    width: int
    height: int
    size_bytes: int

    @computed_field
    @property
    def url(self) -> str:
        return f"/listing/{self.listing_id}/photos/{self.photo_id}"


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
    material_or_product: SafeText
    specifications: dict[SafeText, SafeText] = {}


class ListingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: Stream | None = None
    material_or_product: SafeText | None = None
    specifications: dict[SafeText, SafeText] | None = None
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
    photos: list[ListingPhotoRead] = []
    status: ListingStatus = ListingStatus.DRAFT
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
