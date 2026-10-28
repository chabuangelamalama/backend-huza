import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.payment_config import MomoSettings
from models import Notification, Payment, PaymentEvent
from models.business import ApprovalStatus, BusinessRole
from models.enquiry import EnquiryStatus, FailureReason
from models.notification import NotificationEvent
from models.payment import PaymentStatus, PayoutStatus, RefundStatus
from models.user import User, UserRole
from repositories import payment_repository as repo
from schemas.payment import normalize_msisdn, safe_reason
from services.money import split_fee
from services.momo import (
    MomoGateway,
    MomoRejected,
    MomoResult,
    MomoTransient,
    verify_callback_token,
)

log = logging.getLogger("huza.payments")

_NOT_FOUND = ("not_found", "Payment or enquiry not found")
_RACE_GUARD_SECONDS = 60  

_poll_lock = threading.Lock()
_last_poll: dict[UUID, float] = {}


class PaymentError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, **extra):
        super().__init__(
            status_code=status_code,
            detail={"code": code, "message": message, **extra},
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mask(phone: str) -> str:
    return f"{phone[:3]}****{phone[-3:]}"


class PaymentService:
    def __init__(self, db: Session, momo: MomoGateway, settings: MomoSettings):
        self.db = db
        self.momo = momo
        self.s = settings

    # ------------------------------------------------------------------ authz
    @staticmethod
    def _side(actor: User, enquiry) -> str | None:
        if enquiry is None:
            return None
        if actor.user_role == UserRole.ADMIN:
            return "admin"
        if actor.business_id is None:
            return None
        if actor.business_id == enquiry.buyer_business_id:
            return "buyer"
        if actor.business_id == enquiry.seller_business_id:
            return "seller"
        return None

    def _require(self, actor: User, enquiry, allowed: set[str]) -> str:
        side = self._side(actor, enquiry)
        if side not in allowed:
            raise PaymentError(404, *_NOT_FOUND)
        return side

    @staticmethod
    def _require_admin(actor: User) -> None:
        if actor.user_role != UserRole.ADMIN:
            raise PaymentError(403, "forbidden", "Administrators only")

    # ------------------------------------------------------------ audit + alerts
    def _event(
        self,
        event_type: str,
        *,
        payment_id: UUID | None = None,
        business_id: UUID | None = None,
        actor: User | None = None,
        **detail,
    ) -> None:
        """Added to the CURRENT transaction. Never put phone numbers in detail."""
        self.db.add(
            PaymentEvent(
                payment_id=payment_id,
                business_id=business_id,
                actor_user_id=actor.user_id if actor else None,
                event_type=event_type,
                detail={k: str(v) for k, v in detail.items()},
            )
        )

    def _notify(
        self, business_id: UUID, event: NotificationEvent, enquiry_id: UUID
    ) -> None:
        # Alerts carry the event type and ids only: no prices, names or phone numbers.
        for user in repo.business_users(self.db, business_id):
            self.db.add(
                Notification(
                    user_id=user.user_id, event_type=event, enquiry_id=enquiry_id
                )
            )

    # --------------------------------------------------------- buyer: initiate
    def initiate_payment(
        self, actor: User, enquiry_id: UUID, payer_phone: str
    ) -> Payment:
        enquiry = repo.get_enquiry(self.db, enquiry_id)
        self._require(actor, enquiry, {"buyer"})

        # Settle earlier attempts first (outside the lock: this calls MTN).
        for old in repo.pending_for_enquiry(self.db, enquiry_id):
            self.reconcile_payment(old.payment_id)

        enquiry = repo.get_enquiry(
            self.db, enquiry_id, lock=True
        )  # serialise "pay" clicks
        try:
            self._check_can_pay(actor, enquiry, payer_phone)
            payment = Payment(
                enquiry_id=enquiry.enquiry_id,
                amount=enquiry.total_amount, 
                payer_phone=payer_phone,
                reference_id=str(uuid.uuid4()),
            )
            self.db.add(payment)
            self.db.flush()
            self._event(
                "PAYMENT_CREATED",
                payment_id=payment.payment_id,
                business_id=enquiry.buyer_business_id,
                actor=actor,
                amount=enquiry.total_amount,
            )
            self.db.commit()
        except IntegrityError:
            self.db.rollback()  
            raise PaymentError(
                409,
                "payment_in_progress",
                "A payment for this enquiry is already in progress",
            )
        except PaymentError:
            self.db.rollback()
            raise

        log.info(
            "payment created payment_id=%s enquiry_id=%s payer=%s",
            payment.payment_id,
            enquiry_id,
            _mask(payer_phone),
        )
        self._send_request_to_pay(payment.payment_id)
        return repo.get_payment(self.db, payment.payment_id)

    def _registered_phones(self, actor: User, buyer) -> set[str]:
        found = set()
        for raw in (actor.phone, buyer.contact_phone):
            if raw:
                try:
                    found.add(normalize_msisdn(raw))
                except ValueError:
                    pass
        return found

    def _check_can_pay(self, actor: User, enquiry, payer_phone: str) -> None:
        if enquiry.status != EnquiryStatus.AGREED:
            raise PaymentError(
                409,
                "enquiry_not_payable",
                "The seller must accept the enquiry before you can pay",
            )
        buyer = repo.get_business(self.db, enquiry.buyer_business_id)
        seller = repo.get_business(self.db, enquiry.seller_business_id)
        if buyer.approval_status != ApprovalStatus.APPROVED:
            raise PaymentError(
                403, "business_not_approved", "Your business is not approved"
            )
        if seller.approval_status != ApprovalStatus.APPROVED:
            raise PaymentError(
                409, "seller_unavailable", "The seller cannot receive payments now"
            )
        if not (seller.payout_phone and seller.payout_network):
            raise PaymentError(
                409,
                "seller_payout_not_configured",
                "The seller has not set up payout details yet",
            )
        if (
            self.s.require_registered_payer_phone
            and payer_phone not in self._registered_phones(actor, buyer)
        ):
            raise PaymentError(
                422,
                "payer_phone_not_registered",
                "Pay from the phone number saved on your profile, or update your profile",
            )
        amount: Decimal = enquiry.total_amount
        if amount <= 0 or amount != amount.to_integral_value():
            raise PaymentError(
                409, "invalid_amount", "This enquiry has an invalid total"
            )
        listing = repo.get_listing(self.db, enquiry.listing_id)
        if listing is None or listing.quantity < enquiry.quantity:
            raise PaymentError(
                409, "quantity_unavailable", "The seller no longer has enough stock"
            )

        # ---- abuse limits ----
        if (
            repo.count_attempts_for_enquiry(self.db, enquiry.enquiry_id)
            >= self.s.max_attempts_per_enquiry
        ):
            raise PaymentError(
                429, "too_many_attempts", "Too many payment attempts for this enquiry"
            )
        last = repo.last_attempt_time(self.db, enquiry.enquiry_id)
        if last and (_now() - last).total_seconds() < self.s.attempt_cooldown_seconds:
            raise PaymentError(
                429, "cooldown", "Please wait a moment before trying again"
            )
        since = _now() - timedelta(hours=1)
        if (
            repo.count_attempts_by_buyer_since(
                self.db, enquiry.buyer_business_id, since
            )
            >= self.s.max_attempts_per_business_per_hour
        ):
            raise PaymentError(
                429, "too_many_attempts", "Too many payment attempts, try later"
            )
        if (
            repo.count_attempts_by_phone_since(self.db, payer_phone, since)
            >= self.s.max_attempts_per_payer_phone_per_hour
        ):
            raise PaymentError(
                429, "too_many_attempts", "Too many requests to this number, try later"
            )

    def _send_request_to_pay(self, payment_id: UUID) -> None:
        p = repo.get_payment(self.db, payment_id)
        try:
            self.momo.request_to_pay(
                reference_id=p.reference_id,
                amount=p.amount,
                payer_msisdn=p.payer_phone,
                external_id=str(p.payment_id),
                payer_message="HUZA payment",
                payee_note=f"HUZA enquiry {str(p.enquiry_id)[:8]}",
            )
        except MomoRejected as e:
            self._mark_failed(payment_id, safe_reason(e.reason))
        except MomoTransient:
            log.warning("momo request_to_pay outcome unknown payment_id=%s", payment_id)

    # ------------------------------------------------------- collection result
    def reconcile_payment(self, payment_id: UUID) -> Payment | None:
        payment = repo.get_payment(self.db, payment_id)
        if payment is None or payment.status != PaymentStatus.PENDING:
            return payment
        try:
            result = self.momo.get_request_to_pay(payment.reference_id)
        except MomoTransient:
            return payment
        if result is None:
            if (_now() - payment.created_at).total_seconds() > _RACE_GUARD_SECONDS:
                self._mark_failed(payment_id, "NOT_FOUND_AT_MTN")
        elif result.status == "FAILED":
            self._mark_failed(payment_id, safe_reason(result.reason))
        elif result.status == "SUCCESSFUL":
            if self._matches(result, payment.amount, str(payment.payment_id)):
                self._apply_success(payment_id, result)
            else:
                self._mismatch(payment_id, "collection")
        return repo.get_payment(self.db, payment_id)

    def _matches(self, r: MomoResult, amount: Decimal, external_id: str) -> bool:
        return (
            r.amount is not None
            and r.amount == amount
            and r.currency == self.s.currency
            and r.external_id == external_id
        )

    def _mismatch(self, payment_id: UUID, kind: str) -> None:
        p = repo.get_payment(self.db, payment_id, lock=True)
        p.needs_review = True
        p.review_reason = f"MTN {kind} result does not match our record"
        self._event("MOMO_MISMATCH", payment_id=payment_id, kind=kind)
        self.db.commit()
        log.critical(
            "MoMo %s result does not match our record payment_id=%s", kind, payment_id
        )

    def _mark_failed(self, payment_id: UUID, reason: str) -> None:
        p = repo.get_payment(self.db, payment_id, lock=True)
        if p is None or p.status != PaymentStatus.PENDING:
            self.db.rollback()
            return
        p.status = PaymentStatus.FAILED
        p.failure_reason = reason
        enquiry = repo.get_enquiry(self.db, p.enquiry_id)
        self._event("PAYMENT_FAILED", payment_id=payment_id, reason=reason)
        self._notify(
            enquiry.buyer_business_id,
            NotificationEvent.PAYMENT_FAILED,
            enquiry.enquiry_id,
        )
        self.db.commit()
        log.info("payment failed payment_id=%s reason=%s", payment_id, reason)

    def _apply_success(self, payment_id: UUID, result: MomoResult) -> None:
        first = repo.get_payment(self.db, payment_id)
        enquiry = repo.get_enquiry(self.db, first.enquiry_id, lock=True)
        listing = repo.get_listing(self.db, enquiry.listing_id, lock=True)
        p = repo.get_payment(self.db, payment_id, lock=True)
        if p.status != PaymentStatus.PENDING:  # duplicate callback / poll
            self.db.rollback()
            return

        p.status = PaymentStatus.SUCCESSFUL
        p.momo_transaction_id = result.financial_transaction_id
        p.paid_at = _now()
        p.failure_reason = None
        fee, payout = split_fee(p.amount, self.s.huza_fee_percent)
        p.fee_amount, p.payout_amount = fee, payout

        problem = None
        if enquiry.status != EnquiryStatus.AGREED:
            problem = f"CONFLICT: enquiry was {enquiry.status} when payment arrived"
        elif listing.quantity < enquiry.quantity:
            problem = "CONFLICT: listing stock is lower than the paid quantity"

        pay_now = False
        if problem:
            p.needs_review = True
            p.review_reason = problem[:200]
            self._event("PAYMENT_NEEDS_REVIEW", payment_id=payment_id, reason=problem)
            log.critical("PAYMENT NEEDS REVIEW payment_id=%s: %s", payment_id, problem)
        else:
            enquiry.status = EnquiryStatus.PAID
            listing.quantity = listing.quantity - enquiry.quantity
            p.stock_deducted = True
            if self.s.payout_trigger == "ON_PAID":
                p.payout_status = PayoutStatus.PENDING
                pay_now = self.s.auto_payout
                self._event("PAYOUT_QUEUED", payment_id=payment_id, trigger="ON_PAID")

        self._event("PAYMENT_SUCCEEDED", payment_id=payment_id, fee=fee, payout=payout)
        self._notify(
            enquiry.buyer_business_id,
            NotificationEvent.PAYMENT_SUCCEEDED,
            enquiry.enquiry_id,
        )
        self._notify(
            enquiry.seller_business_id,
            NotificationEvent.PAYMENT_SUCCEEDED,
            enquiry.enquiry_id,
        )
        self.db.commit()
        log.info("payment successful payment_id=%s", payment_id)

        try:
            if problem and self.s.auto_refund_on_conflict:
                self.refund_payment(None, payment_id)
            elif pay_now:
                self.initiate_payout(None, payment_id)
        except Exception:  # a follow-up hiccup must never hide a recorded payment
            log.exception("follow-up after payment failed payment_id=%s", payment_id)

    # ----------------------------------------------------- receipt -> payout due
    def confirm_receipt(self, actor: User, enquiry_id: UUID) -> Payment:
        """Buyer says the goods arrived: enquiry PAID -> COMPLETED, seller becomes payable."""
        enquiry = repo.get_enquiry(self.db, enquiry_id)
        self._require(actor, enquiry, {"buyer"})
        payment = self._complete_enquiry(enquiry_id, actor, source="BUYER")
        return payment

    def _complete_enquiry(
        self, enquiry_id: UUID, actor: User | None, source: str
    ) -> Payment:
        enquiry = repo.get_enquiry(self.db, enquiry_id, lock=True)
        payment = repo.successful_payment_for_enquiry(self.db, enquiry_id)
        if (
            enquiry.status != EnquiryStatus.PAID
            or payment is None
            or payment.refund_status != RefundStatus.NONE
        ):
            self.db.rollback()
            raise PaymentError(
                409, "not_completable", "This enquiry is not waiting for confirmation"
            )
        enquiry.status = EnquiryStatus.COMPLETED
        enquiry.closed_at = _now()
        self._event(
            "RECEIPT_CONFIRMED",
            payment_id=payment.payment_id,
            actor=actor,
            source=source,
        )
        self._notify(
            enquiry.seller_business_id, NotificationEvent.STATUS_CHANGED, enquiry_id
        )
        self.db.commit()
        return self.release_payout(enquiry_id)

    def release_payout(self, enquiry_id: UUID) -> Payment | None:
        """Make the seller payable. The enquiry module MUST call this whenever it sets an
        enquiry to COMPLETED by any other route. Safe to call twice."""
        first = repo.successful_payment_for_enquiry(self.db, enquiry_id)
        if first is None:
            return None
        p = repo.get_payment(self.db, first.payment_id, lock=True)
        if (
            p.payout_status != PayoutStatus.NOT_DUE
            or not p.stock_deducted
            or p.refund_status != RefundStatus.NONE
        ):
            self.db.rollback()
            return p
        p.payout_status = PayoutStatus.PENDING
        self._event("PAYOUT_QUEUED", payment_id=p.payment_id, trigger="COMPLETED")
        self.db.commit()
        if self.s.auto_payout:
            return self.initiate_payout(None, p.payment_id)
        return repo.get_payment(self.db, p.payment_id)

    # ------------------------------------------------------------------ payout
    def initiate_payout(self, actor: User | None, payment_id: UUID) -> Payment:
        """actor=None is the system (auto payout / sweeper). Otherwise admin only."""
        if actor is not None:
            self._require_admin(actor)
        p = repo.get_payment(self.db, payment_id, lock=True)
        if p is None:
            self.db.rollback()
            raise PaymentError(404, *_NOT_FOUND)
        allowed = {PayoutStatus.PENDING, PayoutStatus.FAILED}
        if actor is not None:
            allowed.add(PayoutStatus.NOT_DUE)  # admin may release early
        if (
            p.status != PaymentStatus.SUCCESSFUL
            or not p.stock_deducted
            or p.refund_status != RefundStatus.NONE
            or p.payout_status not in allowed
        ):
            self.db.rollback()
            raise PaymentError(
                409, "payout_not_allowed", "This payment cannot be paid out now"
            )
        if p.payout_status == PayoutStatus.PENDING and p.payout_reference:
            self.db.rollback()  # already sent to MTN: read its status instead
            return self.reconcile_payout(payment_id)

        enquiry = repo.get_enquiry(self.db, p.enquiry_id)
        seller = repo.get_business(self.db, enquiry.seller_business_id)
        if not (seller.payout_phone and seller.payout_network):
            self.db.rollback()
            raise PaymentError(
                409, "seller_payout_not_configured", "Seller has no payout details"
            )
        hold = repo.payout_hold_until(
            self.db, seller.business_id, self.s.payout_change_hold_hours
        )
        if hold and hold > _now():
            self.db.rollback()
            if actor is not None:
                raise PaymentError(
                    409,
                    "payout_on_hold",
                    "The seller changed payout details recently",
                    until=hold.isoformat(),
                )
            log.info("payout held payment_id=%s until=%s", payment_id, hold)
            return repo.get_payment(self.db, payment_id)

        # A FAILED payout gets a NEW reference: MTN rejects re-use of a failed one.
        p.payout_reference = str(uuid.uuid4())
        p.payout_status = PayoutStatus.PENDING
        p.payout_failure_reason = None
        ref = p.payout_reference
        amount = p.payout_amount if p.payout_amount is not None else p.amount
        payee = seller.payout_phone
        self._event("PAYOUT_STARTED", payment_id=payment_id, actor=actor, amount=amount)
        self.db.commit()  # reference saved BEFORE calling MTN (no double payout on retry)

        try:
            self.momo.transfer(
                reference_id=ref,
                amount=amount,
                payee_msisdn=payee,
                external_id=str(payment_id),
                payer_message="HUZA payout",
                payee_note=f"HUZA enquiry {str(enquiry.enquiry_id)[:8]}",
            )
        except MomoRejected as e:
            self._payout_failed(payment_id, safe_reason(e.reason))
        except MomoTransient:
            log.warning("momo transfer outcome unknown payment_id=%s", payment_id)
        return repo.get_payment(self.db, payment_id)

    def _transfer_outcome(
        self, ref: str, amount: Decimal, external_id: str, since: datetime
    ) -> tuple[str, str | None]:
        """-> (done | failed | pending | missing | mismatch | unknown, reason)"""
        try:
            r = self.momo.get_transfer(ref)
        except MomoTransient:
            return "unknown", None
        if r is None:
            late = (_now() - since).total_seconds() > _RACE_GUARD_SECONDS
            return ("missing" if late else "unknown"), None
        if r.status == "FAILED":
            return "failed", safe_reason(r.reason)
        if r.status == "SUCCESSFUL":
            ok = self._matches(r, amount, external_id)
            return ("done" if ok else "mismatch"), None
        return "pending", None

    def reconcile_payout(self, payment_id: UUID) -> Payment | None:
        p = repo.get_payment(self.db, payment_id)
        if (
            p is None
            or p.status != PaymentStatus.SUCCESSFUL
            or p.payout_status != PayoutStatus.PENDING
            or not p.payout_reference
        ):
            return p
        amount = p.payout_amount if p.payout_amount is not None else p.amount
        outcome, reason = self._transfer_outcome(
            p.payout_reference, amount, str(p.payment_id), p.updated_at
        )
        if outcome == "done":
            self._payout_paid(payment_id)
        elif outcome in ("failed", "missing"):
            self._payout_failed(payment_id, reason or "NOT_FOUND_AT_MTN")
        elif outcome == "mismatch":
            self._mismatch(payment_id, "payout")
        return repo.get_payment(self.db, payment_id)

    def _payout_paid(self, payment_id: UUID) -> None:
        p = repo.get_payment(self.db, payment_id, lock=True)
        if p.payout_status != PayoutStatus.PENDING:
            self.db.rollback()
            return
        p.payout_status = PayoutStatus.PAID
        p.paid_out_at = _now()
        enquiry = repo.get_enquiry(self.db, p.enquiry_id)
        self._event("PAYOUT_PAID", payment_id=payment_id)
        self._notify(
            enquiry.seller_business_id,
            NotificationEvent.PAYOUT_SENT,
            enquiry.enquiry_id,
        )
        self.db.commit()
        log.info("payout paid payment_id=%s", payment_id)

    def _payout_failed(self, payment_id: UUID, reason: str) -> None:
        p = repo.get_payment(self.db, payment_id, lock=True)
        if p.payout_status != PayoutStatus.PENDING:
            self.db.rollback()
            return
        p.payout_status = PayoutStatus.FAILED  # admin can retry (new MTN reference)
        p.payout_failure_reason = reason
        p.needs_review = True
        p.review_reason = f"PAYOUT_FAILED: {reason}"[:200]
        self._event("PAYOUT_FAILED", payment_id=payment_id, reason=reason)
        self.db.commit()
        log.error("payout failed payment_id=%s reason=%s", payment_id, reason)

    # ------------------------------------------------------------------ refund
    def refund_payment(
        self,
        actor: User | None,
        payment_id: UUID,
        failure_reason: FailureReason | None = None,
    ) -> Payment:
        """Send the buyer's money back (Disbursement transfer to the payer number).

        actor=None is the system (conflict refund). Otherwise admin only. Not allowed once
        the seller payout has been sent. If the enquiry is PAID it is CANCELLED and the
        stock is given back.
        """
        if actor is not None:
            self._require_admin(actor)
        first = repo.get_payment(self.db, payment_id)
        if first is None:
            raise PaymentError(404, *_NOT_FOUND)
        enquiry = repo.get_enquiry(self.db, first.enquiry_id, lock=True)
        listing = repo.get_listing(self.db, enquiry.listing_id, lock=True)
        p = repo.get_payment(self.db, payment_id, lock=True)
        if (
            p.status != PaymentStatus.SUCCESSFUL
            or p.refund_status not in (RefundStatus.NONE, RefundStatus.FAILED)
            or p.payout_status == PayoutStatus.PAID
            or (p.payout_status == PayoutStatus.PENDING and p.payout_reference)
            or enquiry.status == EnquiryStatus.COMPLETED
        ):
            self.db.rollback()
            raise PaymentError(
                409, "refund_not_allowed", "This payment cannot be refunded now"
            )

        if enquiry.status == EnquiryStatus.PAID:
            enquiry.status = EnquiryStatus.CANCELLED
            enquiry.failure_reason = failure_reason or FailureReason.PAYMENT
            enquiry.closed_at = _now()
        if p.stock_deducted:
            listing.quantity = listing.quantity + enquiry.quantity
            p.stock_deducted = False

        p.payout_status = PayoutStatus.NOT_DUE
        p.refund_reference = str(uuid.uuid4())
        p.refund_status = RefundStatus.PENDING
        ref, amount, payee = p.refund_reference, p.amount, p.payer_phone
        self._event("REFUND_STARTED", payment_id=payment_id, actor=actor, amount=amount)
        self._notify(
            enquiry.buyer_business_id,
            NotificationEvent.STATUS_CHANGED,
            enquiry.enquiry_id,
        )
        self.db.commit()

        try:
            self.momo.transfer(
                reference_id=ref,
                amount=amount,
                payee_msisdn=payee,
                external_id=f"refund-{payment_id}",
                payer_message="HUZA refund",
                payee_note=f"HUZA enquiry {str(enquiry.enquiry_id)[:8]}",
            )
        except MomoRejected as e:
            self._refund_failed(payment_id, safe_reason(e.reason))
        except MomoTransient:
            log.warning("momo refund outcome unknown payment_id=%s", payment_id)
        return repo.get_payment(self.db, payment_id)

    def reconcile_refund(self, payment_id: UUID) -> Payment | None:
        p = repo.get_payment(self.db, payment_id)
        if (
            p is None
            or p.refund_status != RefundStatus.PENDING
            or not p.refund_reference
        ):
            return p
        outcome, reason = self._transfer_outcome(
            p.refund_reference, p.amount, f"refund-{p.payment_id}", p.updated_at
        )
        if outcome == "done":
            self._refund_done(payment_id)
        elif outcome in ("failed", "missing"):
            self._refund_failed(payment_id, reason or "NOT_FOUND_AT_MTN")
        elif outcome == "mismatch":
            self._mismatch(payment_id, "refund")
        return repo.get_payment(self.db, payment_id)

    def _refund_done(self, payment_id: UUID) -> None:
        p = repo.get_payment(self.db, payment_id, lock=True)
        if p.refund_status != RefundStatus.PENDING:
            self.db.rollback()
            return
        p.refund_status = RefundStatus.REFUNDED
        p.refunded_at = _now()
        enquiry = repo.get_enquiry(self.db, p.enquiry_id)
        self._event("REFUND_DONE", payment_id=payment_id)
        self._notify(
            enquiry.buyer_business_id,
            NotificationEvent.STATUS_CHANGED,
            enquiry.enquiry_id,
        )
        self.db.commit()
        log.info("refund done payment_id=%s", payment_id)

    def _refund_failed(self, payment_id: UUID, reason: str) -> None:
        p = repo.get_payment(self.db, payment_id, lock=True)
        if p.refund_status != RefundStatus.PENDING:
            self.db.rollback()
            return
        p.refund_status = RefundStatus.FAILED
        p.needs_review = True
        p.review_reason = f"REFUND_FAILED: {reason}"[:200]
        self._event("REFUND_FAILED", payment_id=payment_id, reason=reason)
        self.db.commit()
        log.critical(
            "REFUND FAILED payment_id=%s reason=%s (buyer money still held)",
            payment_id,
            reason,
        )

    # -------------------------------------------------------------------- reads
    def _should_poll(self, payment_id: UUID) -> bool:
        now = time.monotonic()
        with _poll_lock:
            if len(_last_poll) > 5000:
                _last_poll.clear()
            if (
                now - _last_poll.get(payment_id, 0)
                < self.s.status_poll_min_interval_seconds
            ):
                return False
            _last_poll[payment_id] = now
            return True

    def get_payment_for_actor(
        self, actor: User, payment_id: UUID
    ) -> tuple[Payment, str]:
        payment = repo.get_payment(self.db, payment_id)
        enquiry = repo.get_enquiry(self.db, payment.enquiry_id) if payment else None
        side = self._require(actor, enquiry, {"buyer", "seller", "admin"})
        if self._should_poll(payment_id):
            if payment.status == PaymentStatus.PENDING:
                payment = self.reconcile_payment(payment_id)
            elif payment.refund_status == RefundStatus.PENDING:
                payment = self.reconcile_refund(payment_id)
            elif (
                payment.payout_status == PayoutStatus.PENDING
                and payment.payout_reference
                and side in ("seller", "admin")
            ):
                payment = self.reconcile_payout(payment_id)
        return payment, side

    def payments_for_enquiry(
        self, actor: User, enquiry_id: UUID
    ) -> tuple[list[Payment], str]:
        enquiry = repo.get_enquiry(self.db, enquiry_id)
        side = self._require(actor, enquiry, {"buyer", "seller", "admin"})
        return repo.payments_for_enquiry(self.db, enquiry_id), side

    def my_payments(self, actor: User, side: str, status, limit: int, offset: int):
        if actor.business_id is None:
            raise PaymentError(403, "forbidden", "Business accounts only")
        return repo.list_for_business(
            self.db,
            actor.business_id,
            side=side,
            status=status,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------- seller: payout info
    def get_payout_details(self, actor: User):
        if actor.business_id is None:
            raise PaymentError(403, "forbidden", "Business accounts only")
        return repo.get_business(self.db, actor.business_id)

    def set_payout_details(self, actor: User, phone: str, network):
        """ALL payout-number changes must go through here (the hold depends on it)."""
        business = self.get_payout_details(actor)
        if business.business_role not in (
            BusinessRole.SUPPLIER,
            BusinessRole.PROCESSOR,
        ):
            raise PaymentError(
                403, "forbidden", "Only suppliers and processors receive payouts"
            )
        try:
            active = self.momo.is_account_active(phone)
        except MomoTransient:
            raise PaymentError(
                503, "momo_unavailable", "Could not check the number, try again"
            )
        if not active:
            raise PaymentError(
                422,
                "payout_number_invalid",
                "That number is not an active MoMo account",
            )
        previous = business.payout_phone
        if previous != phone:
            kind = "PAYOUT_DETAILS_REPLACED" if previous else "PAYOUT_DETAILS_SET"
            self._event(
                kind, business_id=business.business_id, actor=actor, network=network
            )
        business.payout_phone = phone
        business.payout_network = network
        self.db.commit()
        log.info(
            "payout details changed business_id=%s phone=%s",
            business.business_id,
            _mask(phone),
        )
        return business

    # ------------------------------------------------------- callback + admin
    def handle_callback(self, kind: str, reference_id: str, token: str) -> None:
        secret = self.s.callback_secret.get_secret_value()
        if kind not in ("collection", "disbursement") or not verify_callback_token(
            secret, kind, reference_id, token
        ):
            raise PaymentError(404, *_NOT_FOUND)
        # The callback body is ignored on purpose. We ask MTN ourselves.
        if kind == "collection":
            p = repo.get_payment_by_reference(self.db, reference_id)
            if p:
                self.reconcile_payment(p.payment_id)
            return
        p = repo.get_payment_by_payout_reference(self.db, reference_id)
        if p:
            self.reconcile_payout(p.payment_id)
            return
        p = repo.get_payment_by_refund_reference(self.db, reference_id)
        if p:
            self.reconcile_refund(p.payment_id)

    def admin_list(
        self, actor: User, status, payout_status, needs_review, limit: int, offset: int
    ):
        self._require_admin(actor)
        return repo.list_all(
            self.db,
            status=status,
            payout_status=payout_status,
            needs_review=needs_review,
            limit=limit,
            offset=offset,
        )

    def admin_events(self, actor: User, payment_id: UUID):
        self._require_admin(actor)
        return repo.events_for_payment(self.db, payment_id)

    def admin_reconcile(self, actor: User, payment_id: UUID) -> Payment:
        self._require_admin(actor)
        p = repo.get_payment(self.db, payment_id)
        if p is None:
            raise PaymentError(404, *_NOT_FOUND)
        self._reconcile_any(p)
        return repo.get_payment(self.db, payment_id)

    def _reconcile_any(self, p: Payment) -> None:
        if p.status == PaymentStatus.PENDING:
            self.reconcile_payment(p.payment_id)
        if p.refund_status == RefundStatus.PENDING:
            self.reconcile_refund(p.payment_id)
        if p.payout_status == PayoutStatus.PENDING and p.payout_reference:
            self.reconcile_payout(p.payment_id)

    def sweep(self, actor: User | None, limit: int = 50) -> dict[str, int]:
        """Settle stuck money movements. Run every few minutes (Heroku Scheduler runs
        `python -m scripts.sweep_payments`) or call POST /admin/payments/sweep."""
        if actor is not None:
            self._require_admin(actor)
        out = {"checked": 0, "payouts_started": 0, "auto_completed": 0, "flagged": 0}

        for p in repo.unsettled(self.db, _now() - timedelta(seconds=30), limit):
            self._reconcile_any(p)
            out["checked"] += 1

        for p in repo.auto_complete_candidates(
            self.db, _now() - timedelta(days=self.s.auto_release_days), limit
        ):
            try:
                self._complete_enquiry(p.enquiry_id, None, source="AUTO_RELEASE")
                out["auto_completed"] += 1
            except HTTPException:
                log.warning("auto-complete skipped payment_id=%s", p.payment_id)

        for p in repo.payouts_due(self.db, limit):
            if self.s.auto_payout:
                try:
                    self.initiate_payout(None, p.payment_id)
                    out["payouts_started"] += 1
                except HTTPException:
                    log.warning("payout skipped payment_id=%s", p.payment_id)

        cutoff = _now() - timedelta(hours=self.s.stale_pending_review_hours)
        for p in repo.stale_pending(self.db, cutoff, limit):
            locked = repo.get_payment(self.db, p.payment_id, lock=True)
            if locked.status == PaymentStatus.PENDING and not locked.needs_review:
                locked.needs_review = True
                locked.review_reason = "PENDING_TOO_LONG"
                self._event(
                    "PAYMENT_NEEDS_REVIEW",
                    payment_id=p.payment_id,
                    reason="PENDING_TOO_LONG",
                )
                out["flagged"] += 1
            self.db.commit()
        return out
