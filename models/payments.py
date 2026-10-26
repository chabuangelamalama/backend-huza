from sqlalchemy import (
    Column,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin, timestamptz, uuid_pk
from .enums import PaymentStatus, PayoutStatus, payment_status_t, payout_status_t


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    payment_id = uuid_pk()
    enquiry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("enquiries.enquiry_id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount = Column(Numeric(19, 4), nullable=False)
    payer_phone = Column(Text, nullable=False)
    reference_id = Column(String(100), nullable=False, unique=True)
    momo_transaction_id = Column(String(100), nullable=True)
    status = Column(
        payment_status_t,
        nullable=False,
        default=PaymentStatus.PENDING,
        server_default=text("'PENDING'"),
    )
    failure_reason = Column(Text, nullable=True)
    payout_status = Column(
        payout_status_t,
        nullable=False,
        default=PayoutStatus.NOT_DUE,
        server_default=text("'NOT_DUE'"),
    )
    payout_reference = Column(String(100), nullable=True)
    paid_at = timestamptz(nullable=True)
    paid_out_at = timestamptz(nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index(
            "uq_payments_one_pending",
            "enquiry_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            "uq_payments_one_successful",
            "enquiry_id",
            unique=True,
            postgresql_where=text("status = 'SUCCESSFUL'"),
        ),
        Index("ix_payments_enquiry_id", "enquiry_id"),
    )

    enquiry = relationship("Enquiry", back_populates="payments")
