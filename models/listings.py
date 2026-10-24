"""Table 4: listings."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, timestamptz, uuid_pk
from .enums import (
    ListingStatus,
    ListingType,
    SortingStatus,
    Stream,
    Unit,
    listing_status_t,
    listing_type_t,
    sorting_status_t,
    stream_t,
    unit_t,
)

if TYPE_CHECKING:
    from .businesses import Business
    from .locations import Location


class Listing(TimestampMixin, Base):
    """A raw by-product (supplier) or finished product (processor). Only PUBLISHED listings appear in search."""

    __tablename__ = "listings"

    listing_id: Mapped[uuid.UUID] = uuid_pk()
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.business_id", ondelete="RESTRICT"), nullable=False
    )
    listing_type: Mapped[ListingType] = mapped_column(listing_type_t, nullable=False)
    stream: Mapped[Stream] = mapped_column(stream_t, nullable=False)
    material_or_product: Mapped[str] = mapped_column(String(150), nullable=False)
    specifications: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Up to 5 items of {storage_key, content_type, size_bytes}. Files live in file storage.
    photos: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)  # quantity still available
    unit: Mapped[Unit] = mapped_column(unit_t, nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.location_id", ondelete="RESTRICT"), nullable=False
    )
    sorting_status: Mapped[SortingStatus | None] = mapped_column(sorting_status_t, nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)  # RWF, set by the seller
    status: Mapped[ListingStatus] = mapped_column(
        listing_status_t, nullable=False, default=ListingStatus.DRAFT, server_default=text("'DRAFT'")
    )
    published_at: Mapped[datetime | None] = timestamptz(nullable=True)

    __table_args__ = (
        CheckConstraint("jsonb_array_length(photos) <= 5", name="photos_max_5"),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("unit_price > 0", name="unit_price_positive"),
        Index("ix_listings_search", "status", "stream", "listing_type", "location_id"),
        Index("ix_listings_specifications_gin", "specifications", postgresql_using="gin"),
    )

    business: Mapped["Business"] = relationship("Business")
    location: Mapped["Location"] = relationship("Location")
