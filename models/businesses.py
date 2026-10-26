from sqlalchemy import Column, CheckConstraint, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin, timestamptz, uuid_pk
from .enums import (
    ApprovalStatus,
    approval_status_t,
    business_role_t,
    business_type_t,
    payout_network_t,
    supplier_kind_t,
)


class Business(TimestampMixin, Base):
    __tablename__ = "businesses"

    business_id = uuid_pk()
    business_legal_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    business_role = Column(business_role_t, nullable=False)
    business_type = Column(business_type_t, nullable=False)
    supplier_kind = Column(supplier_kind_t, nullable=True)
    location_id = Column(
        UUID(as_uuid=True),
        ForeignKey("locations.location_id", ondelete="RESTRICT"),
        nullable=False,
    )
    streams = Column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    contact_phone = Column(Text, nullable=True)
    contact_email = Column(Text, nullable=False)
    registration_number = Column(String(100), nullable=True)
    approval_status = Column(
        approval_status_t,
        nullable=False,
        default=ApprovalStatus.PENDING,
        server_default=text("'PENDING'"),
    )
    approved_by = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.user_id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_businesses_approved_by_users",
        ),
        nullable=True,
    )
    approved_at = timestamptz(nullable=True)
    rejection_reason = Column(Text, nullable=True)
    payout_phone = Column(Text, nullable=True)
    payout_network = Column(payout_network_t, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "business_type <> 'CONSUMER' OR business_role = 'BUYER'",
            name="consumer_only_buyer",
        ),
        CheckConstraint(
            "supplier_kind IS NULL OR business_role = 'SUPPLIER'",
            name="supplier_kind_only_supplier",
        ),
        CheckConstraint(
            "streams <@ ARRAY['SAWDUST','PLASTIC','GARMENT_OFFCUTS','GLASS']::text[]",
            name="streams_allowed",
        ),
        CheckConstraint(
            "(payout_phone IS NULL) = (payout_network IS NULL)",
            name="payout_phone_with_network",
        ),
    )

    location = relationship("Location")
    user = relationship(
        "User",
        back_populates="business",
        foreign_keys="User.business_id",
        uselist=False,
    )
    approved_by_user = relationship("User", foreign_keys=[approved_by])
