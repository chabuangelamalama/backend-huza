from sqlalchemy import Column, CheckConstraint, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, timestamptz, uuid_pk


class Message(Base):
    __tablename__ = "messages"

    message_id = uuid_pk()
    enquiry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("enquiries.enquiry_id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    body = Column(Text, nullable=False)
    sent_at = timestamptz(nullable=False, server_default=func.now())
    read_at = timestamptz(nullable=True)

    __table_args__ = (
        CheckConstraint("char_length(body) <= 2000", name="body_max_2000"),
    )

    enquiry = relationship("Enquiry", back_populates="messages")
    sender = relationship("User")
