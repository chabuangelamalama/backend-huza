from sqlalchemy import Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .base import Base, uuid_pk


class PaymentEvent(Base):
  

    __tablename__ = "payment_event"

    event_id = uuid_pk()
    payment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("payment.payment_id", ondelete="RESTRICT"),
        nullable=True,
    )
    business_id = Column(
        UUID(as_uuid=True),
        ForeignKey("business.business_id", ondelete="RESTRICT"),
        nullable=True,
    )
    actor_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type = Column(String(50), nullable=False)
    detail = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )

    __table_args__ = (
        Index("ix_payment_events_payment", "payment_id", "created_at"),
        Index("ix_payment_events_business", "business_id", "event_type", "created_at"),
    )
