from sqlalchemy import Column, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, CreatedAtMixin, StrEnum, pg_enum, timestamptz, uuid_pk


class NotificationEvent(StrEnum):
    ENQUIRY_RECEIVED = "ENQUIRY_RECEIVED"
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    STATUS_CHANGED = "STATUS_CHANGED"
    PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYOUT_SENT = "PAYOUT_SENT"
    LISTING_STALE = "LISTING_STALE"
    APPROVAL_DECISION = "APPROVAL_DECISION"


notification_event_t = pg_enum(NotificationEvent, "notification_event")


class Notification(CreatedAtMixin, Base):
    __tablename__ = "notification"

    notification_id = uuid_pk()
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(notification_event_t, nullable=False)
    enquiry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("enquiry.enquiry_id", ondelete="SET NULL"),
        nullable=True,
    )
    listing_id = Column(
        UUID(as_uuid=True),
        ForeignKey("listing.listing_id", ondelete="SET NULL"),
        nullable=True,
    )
    read_at = timestamptz(nullable=True)

    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    user = relationship("User")
    enquiry = relationship("Enquiry")
    listing = relationship("Listing")
