from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import deferred, relationship

from .base import Base, CreatedAtMixin, uuid_pk


class ListingPhoto(CreatedAtMixin, Base):
    __tablename__ = "listing_photo"

    photo_id = uuid_pk()
    listing_id = Column(UUID(as_uuid=True),ForeignKey("listing.listing_id", ondelete="CASCADE"),nullable=False,)
    position = Column(SmallInteger, nullable=False)
    content_type = Column(String(50), nullable=False, server_default=text("'image/webp'") )
    size_bytes = Column(Integer, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    data = deferred(Column(LargeBinary, nullable=False))

    __table_args__ = (
        CheckConstraint("position BETWEEN 1 AND 5", name="position_1_to_5"),
        CheckConstraint("content_type = 'image/webp'", name="content_type_webp"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 5242880", name="size_bytes_range" ),
        CheckConstraint("width > 0 AND height > 0", name="dimensions_positive"),
        UniqueConstraint("listing_id", "position", name="uq_listing_photo_position"),
    )

    listing = relationship("Listing", back_populates="photos")