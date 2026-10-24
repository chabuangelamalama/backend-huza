"""Table 9: notifications."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedAtMixin, timestamptz, uuid_pk
from .enums import NotificationEvent, notification_event_t

if TYPE_CHECKING:
    from .enquiries import Enquiry
    from .listings import Listing
    from .users import User


class Notification(CreatedAtMixin, Base):
    """In-app alert. Text comes from a template and never contains prices, names or contact details."""

    __tablename__ = "notifications"

    notification_id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[NotificationEvent] = mapped_column(notification_event_t, nullable=False)
    enquiry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enquiries.enquiry_id", ondelete="SET NULL"), nullable=True
    )
    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.listing_id", ondelete="SET NULL"), nullable=True
    )
    read_at: Mapped[datetime | None] = timestamptz(nullable=True)

    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    user: Mapped["User"] = relationship("User")
    enquiry: Mapped["Enquiry | None"] = relationship("Enquiry")
    listing: Mapped["Listing | None"] = relationship("Listing")
