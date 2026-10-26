from sqlalchemy import Column, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, CreatedAtMixin, timestamptz, uuid_pk
from .enums import notification_event_t


class Notification(CreatedAtMixin, Base):
    __tablename__ = "notifications"

    notification_id = uuid_pk()
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(notification_event_t, nullable=False)
    enquiry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("enquiries.enquiry_id", ondelete="SET NULL"),
        nullable=True,
    )
    listing_id = Column(
        UUID(as_uuid=True),
        ForeignKey("listings.listing_id", ondelete="SET NULL"),
        nullable=True,
    )
    read_at = timestamptz(nullable=True)

    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    user = relationship("User")
    enquiry = relationship("Enquiry")
    listing = relationship("Listing")
