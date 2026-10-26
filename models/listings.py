from sqlalchemy import (
    Column,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin, timestamptz, uuid_pk
from .enums import (
    ListingStatus,
    listing_status_t,
    listing_type_t,
    sorting_status_t,
    stream_t,
    unit_t,
)


class Listing(TimestampMixin, Base):
    __tablename__ = "listings"

    listing_id = uuid_pk()
    business_id = Column(
        UUID(as_uuid=True),
        ForeignKey("businesses.business_id", ondelete="RESTRICT"),
        nullable=False,
    )
    listing_type = Column(listing_type_t, nullable=False)
    stream = Column(stream_t, nullable=False)
    material_or_product = Column(String(150), nullable=False)
    specifications = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    photos = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    quantity = Column(Numeric(14, 3), nullable=False)
    unit = Column(unit_t, nullable=False)
    location_id = Column(
        UUID(as_uuid=True),
        ForeignKey("locations.location_id", ondelete="RESTRICT"),
        nullable=False,
    )
    sorting_status = Column(sorting_status_t, nullable=True)
    unit_price = Column(Numeric(19, 4), nullable=False)
    status = Column(
        listing_status_t,
        nullable=False,
        default=ListingStatus.DRAFT,
        server_default=text("'DRAFT'"),
    )
    published_at = timestamptz(nullable=True)

    __table_args__ = (
        CheckConstraint("jsonb_array_length(photos) <= 5", name="photos_max_5"),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("unit_price > 0", name="unit_price_positive"),
        Index("ix_listings_search", "status", "stream", "listing_type", "location_id"),
        Index(
            "ix_listings_specifications_gin", "specifications", postgresql_using="gin"
        ),
        UniqueConstraint(
            "listing_id", "business_id", name="uq_listings_listing_business"
        ),
    )

    business = relationship("Business")
    location = relationship("Location")
