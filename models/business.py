from sqlalchemy import Column, CheckConstraint, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import relationship

from .base import Base, StrEnum, TimestampMixin, pg_enum, timestamptz, uuid_pk


class BusinessRole(StrEnum):
    SUPPLIER = "SUPPLIER"
    PROCESSOR = "PROCESSOR"
    BUYER = "BUYER"


class BusinessType(StrEnum):
    BUSINESS = "BUSINESS"
    FARM = "FARM"
    COOPERATIVE = "COOPERATIVE"
    INSTITUTION = "INSTITUTION"
    CONSUMER = "CONSUMER"


class SupplierKind(StrEnum):
    PRODUCER = "PRODUCER"
    COLLECTOR = "COLLECTOR"
    DEALER = "DEALER"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class PayoutNetwork(StrEnum):
    MTN_MOMO = "MTN_MOMO"


business_role_t = pg_enum(BusinessRole, "business_role")
business_type_t = pg_enum(BusinessType, "business_type")
supplier_kind_t = pg_enum(SupplierKind, "supplier_kind")
approval_status_t = pg_enum(ApprovalStatus, "approval_status")
payout_network_t = pg_enum(PayoutNetwork, "payout_network")


class Business(TimestampMixin, Base):
    __tablename__ = "business"

    business_id = uuid_pk()
    business_legal_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    business_role = Column(business_role_t, nullable=False)
    business_type = Column(business_type_t, nullable=False)
    supplier_kind = Column(supplier_kind_t, nullable=True)
    location_id = Column(
        UUID(as_uuid=True),
        ForeignKey("location.location_id", ondelete="RESTRICT"),
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
            "app_user.user_id",
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
