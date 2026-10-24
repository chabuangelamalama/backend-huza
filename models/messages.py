import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, timestamptz, uuid_pk

if TYPE_CHECKING:
    from .enquiries import Enquiry
    from .users import User


class Message(Base):
    __tablename__ = "messages"

    message_id: Mapped[uuid.UUID] = uuid_pk()
    enquiry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enquiries.enquiry_id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = timestamptz(nullable=False, server_default=func.now())
    read_at: Mapped[datetime | None] = timestamptz(nullable=True)

    __table_args__ = (
        CheckConstraint("char_length(body) <= 2000", name="body_max_2000"),
    )

    enquiry: Mapped["Enquiry"] = relationship("Enquiry", back_populates="messages")
    sender: Mapped["User | None"] = relationship("User")
