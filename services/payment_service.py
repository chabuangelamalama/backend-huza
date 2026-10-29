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

from core.payment_config import MpesaSettings
from models import Notification, Payment, PaymentEvent
from models.business import ApprovalStatus, BusinessRole
from models.enquiry import EnquiryStatus, FailureReason
from models.notification import NotificationEvent
from models.payment import PaymentStatus, PayoutStatus, RefundStatus
from models.user import User, UserRole
from repositories import payment_repository as repo
from schemas.payment import normalize_msisdn, safe_reason
from services.money import split_fee
from services.mpesa import (
    MpesaGateway,
    MpesaRejected,
    MpesaResult,
    MpesaTransient,
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
    if not phone or len(phone) < 6:
        return phone or ""
    return f"{phone[:3]}****{phone[-3:]}"


class PaymentService:
    def __init__(self, db: Session, mpesa: MpesaGateway, settings: MpesaSettings):
        self.db = db
        self.mpesa = mpesa
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
        for user in repo.business_users(self.db, business_id):
            self.db.add(
                Notification(
                    user_id=user.user_id, event_type=event, enquiry_id=enquiry_id
                )
            )

    # --------------------------------------------------------- buyer: initiate
    def initiate_payment(
        self, actor: User, enquiry_id: UUID, phone_number: str
    ) -> Payment:
        enquiry = repo.get_enquiry(self.db, enquiry_id)
        self._require(actor, enquiry, {"buyer"})

        for old in repo.pending_for_enquiry(self.db, enquiry_id):
            self.reconcile_payment(old.payment_id)

        enquiry = repo.get_enquiry(self.db, enquiry_id, lock=True)
        try:
            self._check_can_pay(actor, enquiry, phone_number)
            normalized_phone = normalize_msisdn(phone_number)
            payment = Payment(
                enquiry_id=enquiry.enquiry_id,
                amount=enquiry.total_amount,
                phone_number=normalized_phone,
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
            _mask(normalized_phone),
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

    def _check_can_pay(self, actor: User, enquiry, phone_number: str) -> None:
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
            and phone_number not in self._registered_phones(actor, buyer)
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

    def _send_request_to_pay(self, payment_id: UUID) -> None:
        """Invokes the Safaricom M-Pesa client gateway to dispatch the STK push prompt."""
        payment = repo.get_payment(self.db, payment_id)
        if not payment:
            return

        enquiry = repo.get_enquiry(self.db, payment.enquiry_id)
        try:
            checkout_request_id = self.mpesa.request_to_pay(
                reference_id=payment.reference_id,
                amount=payment.amount,
                phone_number=payment.phone_number,
                account_reference=f"ENQ-{str(enquiry.enquiry_id)[:8].upper()}",
                transaction_desc="Athena Payment",
            )
            payment.mpesa_receipt_number = checkout_request_id
            self.db.commit()
        except MpesaRejected as e:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = safe_reason(e.reason)
            self._event(
                "PAYMENT_GATEWAY_REJECTED",
                payment_id=payment.payment_id,
                reason=e.reason,
            )
            self.db.commit()
        except MpesaTransient as e:
            log.warning("Transient M-Pesa error for payment_id=%s: %s", payment_id, e)

    def reconcile_payment(self, payment_id: UUID) -> Payment:
        """Polls the M-Pesa gateway client to reconcile a PENDING transaction's state."""
        payment = repo.get_payment(self.db, payment_id)
        if not payment or payment.status != PaymentStatus.PENDING:
            return payment

        if not payment.mpesa_receipt_number:
            self._send_request_to_pay(payment_id)
            return repo.get_payment(self.db, payment_id)

        try:
            result = self.mpesa.get_request_to_pay(payment.mpesa_receipt_number)
            if not result:
                return payment

            if result.status == "SUCCESSFUL":
                payment.status = PaymentStatus.SUCCESSFUL
                payment.paid_at = _now()
                self._event("PAYMENT_SETTLED", payment_id=payment_id)
                enquiry = repo.get_enquiry(self.db, payment.enquiry_id)
                listing = repo.get_listing(self.db, enquiry.listing_id)
                if listing:
                    listing.quantity -= enquiry.quantity
                    payment.stock_deducted = True
                self.db.commit()
            elif result.status == "FAILED":
                payment.status = PaymentStatus.FAILED
                payment.failure_reason = safe_reason(result.reason)
                self._event(
                    "PAYMENT_FAILED", payment_id=payment_id, reason=result.reason
                )
                self.db.commit()

        except MpesaTransient as e:
            log.warning(
                "Transient M-Pesa status read check error for payment_id=%s: %s",
                payment_id,
                e,
            )

        return payment

    # --------------------------------------------------------- seller payout details
    def get_payout_details(self, actor: User) -> dict:
        if actor.business_id is None:
            raise PaymentError(404, *_NOT_FOUND)
        biz = repo.get_business(self.db, actor.business_id)
        if not biz or not biz.payout_phone:
            raise PaymentError(404, "payout_not_found", "Payout details not found")
        return {
            "payout_phone": _mask(biz.payout_phone),
            "payout_network": getattr(biz, "payout_network", None),
        }

    def set_payout_details(
        self, actor: User, payout_phone: str, payout_network: str | None = None
    ) -> dict:
        if actor.business_id is None:
            raise PaymentError(404, *_NOT_FOUND)
        biz = repo.get_business(self.db, actor.business_id)
        if not biz:
            raise PaymentError(404, "business_not_found", "Business not found")

        normalized = normalize_msisdn(payout_phone)
        biz.payout_phone = normalized
        if payout_network:
            biz.payout_network = payout_network
        self.db.commit()
        return {
            "payout_phone": _mask(normalized),
            "payout_network": getattr(biz, "payout_network", None),
        }

    # --------------------------------------------------------- queries & views
    def get_payment_for_actor(self, actor: User, payment_id: UUID) -> tuple[Payment, str]:
        payment = repo.get_payment(self.db, payment_id)
        if not payment:
            raise PaymentError(404, *_NOT_FOUND)
        enquiry = repo.get_enquiry(self.db, payment.enquiry_id)
        side = self._require(actor, enquiry, {"buyer", "seller", "admin"})
        return payment, side

    def get_payment_for_enquiry(self, actor: User, enquiry_id: UUID) -> tuple[Payment, str]:
        enquiry = repo.get_enquiry(self.db, enquiry_id)
        side = self._require(actor, enquiry, {"buyer", "seller", "admin"})
        payment = repo.get_payment_by_enquiry_id(self.db, enquiry_id)
        if not payment:
            raise PaymentError(404, *_NOT_FOUND)
        return payment, side

    def my_payments(
        self,
        actor: User,
        side: str,
        payment_status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Payment]:
        if actor.user_role == UserRole.ADMIN:
            return repo.list_payments(self.db, payment_status=payment_status, limit=limit, offset=offset)
        if not actor.business_id:
            return []
        return repo.list_payments_for_business(
            self.db,
            business_id=actor.business_id,
            side=side,
            payment_status=payment_status,
            limit=limit,
            offset=offset,
        )

    def confirm_receipt(self, actor: User, enquiry_id: UUID) -> Payment:
        enquiry = repo.get_enquiry(self.db, enquiry_id)
        self._require(actor, enquiry, {"buyer"})
        payment = repo.get_payment_by_enquiry_id(self.db, enquiry_id)
        if not payment:
            raise PaymentError(404, *_NOT_FOUND)
        payment.payout_status = PayoutStatus.DUE
        self.db.commit()
        return payment

    # --------------------------------------------------------- admin actions
    def admin_list(
        self,
        actor: User,
        payment_status: str | None = None,
        payout_status: str | None = None,
        needs_review: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Payment]:
        self._require_admin(actor)
        return repo.list_payments(
            self.db,
            payment_status=payment_status,
            payout_status=payout_status,
            needs_review=needs_review,
            limit=limit,
            offset=offset,
        )

    def sweep(self, actor: User) -> dict:
        self._require_admin(actor)
        count = 0
        for p in repo.list_pending_payments(self.db):
            self.reconcile_payment(p.payment_id)
            count += 1
        return {"checked": count}

    def admin_reconcile(self, actor: User, payment_id: UUID) -> Payment:
        self._require_admin(actor)
        return self.reconcile_payment(payment_id)

    def admin_events(self, actor: User, payment_id: UUID) -> list[PaymentEvent]:
        self._require_admin(actor)
        return repo.list_payment_events(self.db, payment_id)

    def refund_payment(self, actor: User, payment_id: UUID, failure_reason: str | None) -> Payment:
        self._require_admin(actor)
        payment = repo.get_payment(self.db, payment_id)
        if not payment:
            raise PaymentError(404, *_NOT_FOUND)
        payment.refund_status = RefundStatus.REFUNDED
        payment.failure_reason = safe_reason(failure_reason)
        self.db.commit()
        return payment

    def initiate_payout(self, actor: User, payment_id: UUID) -> Payment:
        self._require_admin(actor)
        payment = repo.get_payment(self.db, payment_id)
        if not payment:
            raise PaymentError(404, *_NOT_FOUND)
        payment.payout_status = PayoutStatus.PROCESSING
        self.db.commit()
        return payment

    def handle_callback(self, kind: str, reference_id: str, token: str) -> None:
        pass
