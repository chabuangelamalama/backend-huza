from sqlalchemy import (
    Column,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin, timestamptz, uuid_pk
from .enums import (
    EnquiryStatus,
    enquiry_status_t,
    failure_reason_t,
    unit_t,
)


class Enquiry(TimestampMixin, Base):
    __tablename__ = "enquiries"

    enquiry_id = uuid_pk()
    listing_id = Column(
        UUID(as_uuid=True),
        ForeignKey("listings.listing_id", ondelete="RESTRICT"),
        nullable=False,
    )
    buyer_business_id = Column(
        UUID(as_uuid=True),
        ForeignKey("businesses.business_id", ondelete="RESTRICT"),
        nullable=False,
    )
    seller_business_id = Column(
        UUID(as_uuid=True),
        ForeignKey("businesses.business_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status = Column(
        enquiry_status_t,
        nullable=False,
        default=EnquiryStatus.ENQUIRY,
        server_default=text("'ENQUIRY'"),
    )
    quantity = Column(Numeric(14, 3), nullable=False)
    unit = Column(unit_t, nullable=False)
    unit_price = Column(Numeric(19, 4), nullable=False)
    total_amount = Column(Numeric(19, 4), nullable=False)
    failure_reason = Column(failure_reason_t, nullable=True)
    first_response_at = timestamptz(nullable=True)
    accepted_at = timestamptz(nullable=True)
    closed_at = timestamptz(nullable=True)

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

    listing = relationship("Listing", foreign_keys=[listing_id])
    buyer = relationship("Business", foreign_keys=[buyer_business_id])
    seller = relationship("Business", foreign_keys=[seller_business_id])
    messages = relationship("Message", back_populates="enquiry", passive_deletes=True)
    payments = relationship("Payment", back_populates="enquiry")
