import enum

from sqlalchemy import Enum as SAEnum


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:
        return self.value


class UserRole(StrEnum):
    BUSINESS_USER = "BUSINESS_USER"
    ADMIN = "ADMIN"


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


class OsmType(StrEnum):
    NODE = "NODE"
    WAY = "WAY"
    RELATION = "RELATION"


class Stream(StrEnum):
    SAWDUST = "SAWDUST"
    PLASTIC = "PLASTIC"
    GARMENT_OFFCUTS = "GARMENT_OFFCUTS"
    GLASS = "GLASS"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class PayoutNetwork(StrEnum):
    MTN_MOMO = "MTN_MOMO"


class ListingType(StrEnum):
    RAW_BYPRODUCT = "RAW_BYPRODUCT"
    FINISHED_PRODUCT = "FINISHED_PRODUCT"


class Unit(StrEnum):
    TONNE = "TONNE"
    KILOGRAM = "KILOGRAM"
    TRUCKLOAD = "TRUCKLOAD"
    PIECE = "PIECE"
    BAG = "BAG"


class SortingStatus(StrEnum):
    SORTED = "SORTED"
    PARTLY_SORTED = "PARTLY_SORTED"
    MIXED = "MIXED"


class ListingStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class EnquiryStatus(StrEnum):
    ENQUIRY = "ENQUIRY"
    AGREED = "AGREED"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    UNSUCCESSFUL = "UNSUCCESSFUL"


class FailureReason(StrEnum):
    NO_PARTNER_FOUND = "NO_PARTNER_FOUND"
    QUALITY = "QUALITY"
    PRICE = "PRICE"
    TRANSPORT = "TRANSPORT"
    QUANTITY = "QUANTITY"
    TRUST = "TRUST"
    PAYMENT = "PAYMENT"
    DECLINED = "DECLINED"
    OTHER = "OTHER"


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


class NotificationEvent(StrEnum):
    ENQUIRY_RECEIVED = "ENQUIRY_RECEIVED"
    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    STATUS_CHANGED = "STATUS_CHANGED"
    PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYOUT_SENT = "PAYOUT_SENT"
    LISTING_STALE = "LISTING_STALE"
    APPROVAL_DECISION = "APPROVAL_DECISION"


def _pg_enum(cls: type[enum.Enum], name: str) -> SAEnum:
    """Native PostgreSQL ENUM that stores the member *values*."""
    return SAEnum(
        cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


user_role_t = _pg_enum(UserRole, "user_role")
business_role_t = _pg_enum(BusinessRole, "business_role")
business_type_t = _pg_enum(BusinessType, "business_type")
supplier_kind_t = _pg_enum(SupplierKind, "supplier_kind")
stream_t = _pg_enum(Stream, "stream")
approval_status_t = _pg_enum(ApprovalStatus, "approval_status")
osm_type_t = _pg_enum(OsmType, "osm_type")
payout_network_t = _pg_enum(PayoutNetwork, "payout_network")
listing_type_t = _pg_enum(ListingType, "listing_type")
unit_t = _pg_enum(Unit, "unit")
sorting_status_t = _pg_enum(SortingStatus, "sorting_status")
listing_status_t = _pg_enum(ListingStatus, "listing_status")
enquiry_status_t = _pg_enum(EnquiryStatus, "enquiry_status")
failure_reason_t = _pg_enum(FailureReason, "failure_reason")
payment_status_t = _pg_enum(PaymentStatus, "payment_status")
payout_status_t = _pg_enum(PayoutStatus, "payout_status")
notification_event_t = _pg_enum(NotificationEvent, "notification_event")
