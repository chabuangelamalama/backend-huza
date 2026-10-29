from sqlalchemy import Column, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin, uuid_pk


class Message(TimestampMixin, Base):
    __tablename__ = "message"

    message_id = uuid_pk()
    enquiry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("enquiry.enquiry_id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_business_id = Column(
        UUID(as_uuid=True),
        ForeignKey("business.business_id", ondelete="RESTRICT"),
        nullable=False,
    )
    content = Column(String, nullable=False)

    __table_args__ = (Index("ix_message_enquiry_created", "enquiry_id", "created_at"),)

    enquiry = relationship("Enquiry", foreign_keys=[enquiry_id])
    sender = relationship("Business", foreign_keys=[sender_business_id])
