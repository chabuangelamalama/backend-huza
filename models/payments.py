"""Table 8: payments."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, timestamptz, uuid_pk
from .enums import PaymentStatus, PayoutStatus, payment_status_t, payout_status_t

if TYPE_CHECKING:
    from .enquiries import Enquiry


class Payment(TimestampMixin, Base):
    """One MTN MoMo payment attempt for an enquiry. Failed attempts stay on record; the buyer can retry."""

    __tablename__ = "payments"

    payment_id: Mapped[uuid.UUID] = uuid_pk()
    enquiry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enquiries.enquiry_id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False) 
    payer_phone: Mapped[str] = mapped_column(Text, nullable=False)
    reference_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)  
    momo_transaction_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[PaymentStatus] = mapped_column(
        payment_status_t, nullable=False, default=PaymentStatus.PENDING, server_default=text("'PENDING'")
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payout_status: Mapped[PayoutStatus] = mapped_column(
        payout_status_t, nullable=False, default=PayoutStatus.NOT_DUE, server_default=text("'NOT_DUE'")
    )
    payout_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paid_at: Mapped[datetime | None] = timestamptz(nullable=True)
    paid_out_at: Mapped[datetime | None] = timestamptz(nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),

        Index("uq_payments_one_pending", "enquiry_id", unique=True, postgresql_where=text("status = 'PENDING'")),
        Index("uq_payments_one_successful", "enquiry_id", unique=True, postgresql_where=text("status = 'SUCCESSFUL'")),
        Index("ix_payments_enquiry_id", "enquiry_id"),
    )

    enquiry: Mapped["Enquiry"] = relationship("Enquiry", back_populates="payments")
