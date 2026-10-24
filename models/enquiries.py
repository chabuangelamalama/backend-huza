import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, timestamptz, uuid_pk
from .enums import (
    EnquiryStatus,
    FailureReason,
    Unit,
    enquiry_status_t,
    failure_reason_t,
    unit_t,
)

if TYPE_CHECKING:
    from .businesses import Business
    from .listings import Listing
    from .messages import Message
    from .payments import Payment


class Enquiry(TimestampMixin, Base):
    __tablename__ = "enquiries"

    enquiry_id: Mapped[uuid.UUID] = uuid_pk()
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("listings.listing_id", ondelete="RESTRICT"),
        nullable=False,
    )
    buyer_business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.business_id", ondelete="RESTRICT"),
        nullable=False,
    )
    seller_business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.business_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[EnquiryStatus] = mapped_column(
        enquiry_status_t,
        nullable=False,
        default=EnquiryStatus.ENQUIRY,
        server_default=text("'ENQUIRY'"),
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[Unit] = mapped_column(unit_t, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    failure_reason: Mapped[FailureReason | None] = mapped_column(
        failure_reason_t, nullable=True
    )
    first_response_at: Mapped[datetime | None] = timestamptz(nullable=True)
    accepted_at: Mapped[datetime | None] = timestamptz(nullable=True)
    closed_at: Mapped[datetime | None] = timestamptz(nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["listing_id", "seller_business_id"],
            ["listings.listing_id", "listings.business_id"],
            ondelete="RESTRICT",
            name="fk_enquiries_seller_owns_listing",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price > 0", name="unit_price_positive"),
        CheckConstraint("total_amount > 0", name="total_amount_positive"),
        CheckConstraint(
            "seller_business_id <> buyer_business_id", name="buyer_not_seller"
        ),
        CheckConstraint(
            "(status IN ('CANCELLED', 'UNSUCCESSFUL')) = (failure_reason IS NOT NULL)",
            name="failure_reason_required",
        ),
        Index(
            "uq_enquiries_open_per_buyer",
            "listing_id",
            "buyer_business_id",
            unique=True,
            postgresql_where=text("status IN ('ENQUIRY', 'AGREED', 'PAID')"),
        ),
        Index("ix_enquiries_buyer_status", "buyer_business_id", "status"),
        Index("ix_enquiries_seller_status", "seller_business_id", "status"),
    )

    listing: Mapped["Listing"] = relationship("Listing", foreign_keys=[listing_id])
    buyer: Mapped["Business"] = relationship(
        "Business", foreign_keys=[buyer_business_id]
    )
    seller: Mapped["Business"] = relationship(
        "Business", foreign_keys=[seller_business_id]
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="enquiry", passive_deletes=True
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment", back_populates="enquiry"
    )
