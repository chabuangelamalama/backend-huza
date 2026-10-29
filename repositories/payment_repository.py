"""Database access for payments. No business rules here, only queries."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from models import Business, Enquiry, Listing, Payment, PaymentEvent, User
from models.enquiry import EnquiryStatus
from models.payment import PaymentStatus, PayoutStatus, RefundStatus


def _lock(stmt, lock: bool):
    if lock:
        return stmt.with_for_update().execution_options(populate_existing=True)
    return stmt


def get_enquiry(db: Session, enquiry_id: UUID, *, lock: bool = False) -> Enquiry | None:
    stmt = _lock(select(Enquiry).where(Enquiry.enquiry_id == enquiry_id), lock)
    return db.execute(stmt).scalars().first()


def get_listing(db: Session, listing_id: UUID, *, lock: bool = False) -> Listing | None:
    stmt = _lock(select(Listing).where(Listing.listing_id == listing_id), lock)
    return db.execute(stmt).scalars().first()


def get_business(db: Session, business_id: UUID) -> Business | None:
    return db.get(Business, business_id)


def get_payment(db: Session, payment_id: UUID, *, lock: bool = False) -> Payment | None:
    stmt = _lock(select(Payment).where(Payment.payment_id == payment_id), lock)
    return db.execute(stmt).scalars().first()


def get_payment_by_reference(db: Session, reference_id: str) -> Payment | None:
    stmt = select(Payment).where(Payment.reference_id == reference_id)
    return db.execute(stmt).scalars().first()


def get_payment_by_payout_reference(db: Session, ref: str) -> Payment | None:
    stmt = select(Payment).where(Payment.payout_reference == ref)
    return db.execute(stmt).scalars().first()


def business_users(db: Session, business_id: UUID) -> list[User]:
    return list(
        db.execute(select(User).where(User.business_id == business_id)).scalars()
    )


def payments_for_enquiry(db: Session, enquiry_id: UUID) -> list[Payment]:
    stmt = (
        select(Payment)
        .where(Payment.enquiry_id == enquiry_id)
        .order_by(Payment.created_at.desc())
    )
    return list(db.execute(stmt).scalars())


def pending_for_enquiry(db: Session, enquiry_id: UUID) -> list[Payment]:
    stmt = select(Payment).where(
        Payment.enquiry_id == enquiry_id, Payment.status == PaymentStatus.PENDING
    )
    return list(db.execute(stmt).scalars())


def count_attempts_for_enquiry(db: Session, enquiry_id: UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(Payment)
        .where(Payment.enquiry_id == enquiry_id)
    )
    return db.execute(stmt).scalar_one()


def last_attempt_time(db: Session, enquiry_id: UUID) -> datetime | None:
    stmt = select(func.max(Payment.created_at)).where(Payment.enquiry_id == enquiry_id)
    return db.execute(stmt).scalar_one()


def count_attempts_by_buyer_since(
    db: Session, buyer_business_id: UUID, since: datetime
) -> int:
    stmt = (
        select(func.count())
        .select_from(Payment)
        .join(Enquiry, Enquiry.enquiry_id == Payment.enquiry_id)
        .where(
            Enquiry.buyer_business_id == buyer_business_id, Payment.created_at >= since
        )
    )
    return db.execute(stmt).scalar_one()


def count_attempts_by_phone_since(db: Session, phone: str, since: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(Payment)
        .where(Payment.payer_phone == phone, Payment.created_at >= since)
    )
    return db.execute(stmt).scalar_one()


def list_for_business(
    db: Session,
    business_id: UUID,
    *,
    side: str,
    status: PaymentStatus | None,
    limit: int,
    offset: int,
) -> list[Payment]:
    stmt = select(Payment).join(Enquiry, Enquiry.enquiry_id == Payment.enquiry_id)
    stmt = stmt.where(
        Enquiry.buyer_business_id == business_id
        if side == "buyer"
        else Enquiry.seller_business_id == business_id
    )
    if status:
        stmt = stmt.where(Payment.status == status)
    stmt = stmt.order_by(Payment.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars())


def list_all(
    db: Session,
    *,
    status: PaymentStatus | None,
    payout_status: PayoutStatus | None,
    needs_review: bool | None = None,
    limit: int,
    offset: int,
) -> list[Payment]:
    stmt = select(Payment)
    if needs_review is not None:
        stmt = stmt.where(Payment.needs_review == needs_review)
    if status:
        stmt = stmt.where(Payment.status == status)
    if payout_status:
        stmt = stmt.where(Payment.payout_status == payout_status)
    stmt = stmt.order_by(Payment.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars())


def unsettled(db: Session, older_than: datetime, limit: int) -> list[Payment]:
    """PENDING collections and PENDING payouts that need a status check."""
    stmt = (
        select(Payment)
        .where(
            or_(
                Payment.status == PaymentStatus.PENDING,
                (Payment.status == PaymentStatus.SUCCESSFUL)
                & (Payment.payout_status == PayoutStatus.PENDING)
                & Payment.payout_reference.is_not(None),
                (Payment.refund_status == RefundStatus.PENDING)
                & Payment.refund_reference.is_not(None),
            ),
            Payment.updated_at <= older_than,
        )
        .order_by(Payment.updated_at)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def payouts_due(db: Session, limit: int) -> list[Payment]:
    """Paid by the buyer, payout queued but not yet sent to MTN."""
    stmt = (
        select(Payment)
        .where(
            Payment.status == PaymentStatus.SUCCESSFUL,
            Payment.payout_status == PayoutStatus.PENDING,
            Payment.payout_reference.is_(None),
            Payment.refund_status == RefundStatus.NONE,
        )
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def get_payment_by_refund_reference(db: Session, ref: str) -> Payment | None:
    stmt = select(Payment).where(Payment.refund_reference == ref)
    return db.execute(stmt).scalars().first()


def successful_payment_for_enquiry(db: Session, enquiry_id: UUID) -> Payment | None:
    stmt = select(Payment).where(
        Payment.enquiry_id == enquiry_id, Payment.status == PaymentStatus.SUCCESSFUL
    )
    return db.execute(stmt).scalars().first()


def auto_complete_candidates(
    db: Session, paid_before: datetime, limit: int
) -> list[Payment]:
    """Paid deals the buyer never confirmed, older than the auto-release window."""
    stmt = (
        select(Payment)
        .join(Enquiry, Enquiry.enquiry_id == Payment.enquiry_id)
        .where(
            Payment.status == PaymentStatus.SUCCESSFUL,
            Payment.refund_status == RefundStatus.NONE,
            Payment.stock_deducted.is_(True),
            Payment.paid_at <= paid_before,
            Enquiry.status == EnquiryStatus.PAID,
        )
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def stale_pending(db: Session, created_before: datetime, limit: int) -> list[Payment]:
    stmt = (
        select(Payment)
        .where(
            Payment.status == PaymentStatus.PENDING,
            Payment.needs_review.is_(False),
            Payment.created_at <= created_before,
        )
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


def payout_hold_until(db: Session, business_id: UUID, hours: int) -> datetime | None:
    """When the hold after a payout-number REPLACEMENT ends (None = no hold)."""
    if hours <= 0:
        return None
    stmt = select(func.max(PaymentEvent.created_at)).where(
        PaymentEvent.business_id == business_id,
        PaymentEvent.event_type == "PAYOUT_DETAILS_REPLACED",
    )
    last = db.execute(stmt).scalar_one()
    return last + timedelta(hours=hours) if last else None


def events_for_payment(db: Session, payment_id: UUID) -> list[PaymentEvent]:
    stmt = (
        select(PaymentEvent)
        .where(PaymentEvent.payment_id == payment_id)
        .order_by(PaymentEvent.created_at)
    )
    return list(db.execute(stmt).scalars())


def available_quantity(
    db: Session, listing_id: UUID, *, exclude_enquiry_id: UUID | None = None
) -> Decimal:
    """Stock that can still be promised to a NEW buyer: listing quantity minus the
    quantity of other enquiries that are already AGREED (accepted, not yet paid).

    The accept-enquiry endpoint must call this and refuse to accept more than this.
    """
    listing = get_listing(db, listing_id)
    stmt = select(func.coalesce(func.sum(Enquiry.quantity), 0)).where(
        Enquiry.listing_id == listing_id, Enquiry.status == EnquiryStatus.AGREED
    )
    if exclude_enquiry_id is not None:
        stmt = stmt.where(Enquiry.enquiry_id != exclude_enquiry_id)
    reserved = db.execute(stmt).scalar_one()
    return listing.quantity - Decimal(reserved)
def _to_enum(val, enum_cls):
    if val is None or isinstance(val, enum_cls):
        return val
    try:
        return enum_cls(val)
    except Exception:
        return None


def list_payments(
    db: Session,
    payment_status: str | PaymentStatus | None = None,
    payout_status: str | PayoutStatus | None = None,
    needs_review: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    **kwargs,
) -> list[Payment]:
    status_enum = _to_enum(kwargs.get("status", payment_status), PaymentStatus)
    payout_enum = _to_enum(kwargs.get("payout_status", payout_status), PayoutStatus)
    return list_all(
        db,
        status=status_enum,
        payout_status=payout_enum,
        needs_review=needs_review,
        limit=limit,
        offset=offset,
    )


def list_payments_for_business(
    db: Session,
    business_id: UUID,
    side: str = "buyer",
    payment_status: str | PaymentStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    **kwargs,
) -> list[Payment]:
    target_status = kwargs.get("status", payment_status)
    status_enum = _to_enum(target_status, PaymentStatus)
    return list_for_business(
        db,
        business_id,
        side=side,
        status=status_enum,
        limit=limit,
        offset=offset,
    )
def list_payment_events(db: Session, payment_id: UUID) -> list[PaymentEvent]:
    return events_for_payment(db, payment_id)

def list_pending_payments(db: Session, limit: int = 100) -> list[Payment]:
    stmt = (
        select(Payment)
        .where(Payment.status == PaymentStatus.PENDING)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())
