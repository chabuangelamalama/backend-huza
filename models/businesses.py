"""Table 2: businesses."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, timestamptz, uuid_pk
from .enums import (
    ApprovalStatus,
    BusinessRole,
    BusinessType,
    PayoutNetwork,
    SupplierKind,
    approval_status_t,
    business_role_t,
    business_type_t,
    payout_network_t,
    supplier_kind_t,
)

if TYPE_CHECKING:
    from .locations import Location
    from .users import User


class Business(TimestampMixin, Base):
    """A supplier, processor or buyer. Top-level ownership boundary for access control."""

    __tablename__ = "businesses"

    business_id: Mapped[uuid.UUID] = uuid_pk()
    business_legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_role: Mapped[BusinessRole] = mapped_column(business_role_t, nullable=False)
    business_type: Mapped[BusinessType] = mapped_column(business_type_t, nullable=False)
    supplier_kind: Mapped[SupplierKind | None] = mapped_column(supplier_kind_t, nullable=True)
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.location_id", ondelete="RESTRICT"), nullable=False
    )

    streams: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True) 
    contact_email: Mapped[str] = mapped_column(Text, nullable=False)  
    registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        approval_status_t, nullable=False, default=ApprovalStatus.PENDING, server_default=text("'PENDING'")
    )

    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL", use_alter=True, name="fk_businesses_approved_by_users"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = timestamptz(nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payout_phone: Mapped[str | None] = mapped_column(Text, nullable=True)  
    payout_network: Mapped[PayoutNetwork | None] = mapped_column(payout_network_t, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "business_type <> 'CONSUMER' OR business_role = 'BUYER'", name="consumer_only_buyer"
        ),
        CheckConstraint(
            "supplier_kind IS NULL OR business_role = 'SUPPLIER'", name="supplier_kind_only_supplier"
        ),
        CheckConstraint(
            "streams <@ ARRAY['SAWDUST','PLASTIC','GARMENT_OFFCUTS','GLASS']::text[]", name="streams_allowed"
        ),
        CheckConstraint(
            "(payout_phone IS NULL) = (payout_network IS NULL)", name="payout_phone_with_network"
        ),
    )

    location: Mapped["Location"] = relationship("Location")
    user: Mapped["User | None"] = relationship(
        "User", back_populates="business", foreign_keys="User.business_id", uselist=False
    )
    approved_by_user: Mapped["User | None"] = relationship("User", foreign_keys=[approved_by])
