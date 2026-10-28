from decimal import Decimal

from sqlalchemy import (
    Boolean,
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

from .base import Base, StrEnum, TimestampMixin, pg_enum, timestamptz, uuid_pk


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESSFUL = "SUCCESSFUL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PayoutStatus(StrEnum):
    NOT_DUE = "NOT_DUE"
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"


class RefundStatus(StrEnum):
    NONE = "NONE"
    PENDING = "PENDING"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


payment_status_t = pg_enum(PaymentStatus, "payment_status")
payout_status_t = pg_enum(PayoutStatus, "payout_status")
refund_status_t = pg_enum(RefundStatus, "refund_status")


class Payment(TimestampMixin, Base):
    __tablename__ = "payment"

    payment_id = uuid_pk()
    enquiry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("enquiry.enquiry_id", ondelete="RESTRICT"),
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


    fee_amount = Column(
        Numeric(19, 4),
        nullable=False,
        default=Decimal("0"),
        server_default=text("0"),
    )
    payout_amount = Column(Numeric(19, 4), nullable=True)
    payout_failure_reason = Column(String(100), nullable=True)

   
    stock_deducted = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    
    needs_review = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    review_reason = Column(String(200), nullable=True)
    refund_status = Column(
        refund_status_t,
        nullable=False,
        default=RefundStatus.NONE,
        server_default=text("'NONE'"),
    )
    refund_reference = Column(String(100), nullable=True, unique=True)
    refunded_at = timestamptz(nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("fee_amount >= 0", name="fee_non_negative"),
        CheckConstraint(
            "payout_amount IS NULL OR "
            "(payout_amount > 0 AND payout_amount + fee_amount = amount)",
            name="payout_split_matches_amount",
        ),
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
        Index(
            "ix_payments_needs_review",
            "needs_review",
            postgresql_where=text("needs_review"),
        ),
    )

    enquiry = relationship("Enquiry", back_populates="payments")
