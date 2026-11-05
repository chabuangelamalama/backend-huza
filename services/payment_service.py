import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.payment_config import MpesaSettings
from models import Notification, Payment, PaymentEvent
from models.business import ApprovalStatus, BusinessRole
from models.enquiry import EnquiryStatus
from models.notification import NotificationEvent
from models.payment import PaymentStatus, PayoutStatus
from models.user import User, UserRole
from repositories import payment_repository as repo
from schemas.payment import normalize_msisdn, safe_reason
from services.mpesa import (
    MpesaError,
    MpesaGateway,
    MpesaRejected,
    MpesaTransient,
    verify_callback_token,
)

log = logging.getLogger("huza.payments")

_NOT_FOUND = ("not_found", "Payment or enquiry not found")
_POLL_LOCK = threading.Lock()
_LAST_POLL: dict[UUID, float] = {}


class PaymentError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        **extra,
    ):
        super().__init__(
            status_code=status_code,
            detail={
                "code": code,
                "message": message,
                **extra,
            },
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mask(phone: str | None) -> str:
    if not phone or len(phone) < 6:
        return phone or ""
    return f"{phone[:3]}****{phone[-3:]}"


def _enum_value(value) -> str:
    return str(getattr(value, "value", value))


class PaymentService:
    def __init__(
        self,
        db: Session,
        mpesa: MpesaGateway,
        settings: MpesaSettings,
    ):
        self.db = db
        self.mpesa = mpesa
        self.s = settings

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

    def _require(
        self,
        actor: User,
        enquiry,
        allowed: set[str],
    ) -> str:
        side = self._side(actor, enquiry)
        if side not in allowed:
            raise PaymentError(404, *_NOT_FOUND)
        return side

    @staticmethod
    def _require_admin(actor: User) -> None:
        if actor.user_role != UserRole.ADMIN:
            raise PaymentError(
                403,
                "forbidden",
                "Administrators only",
            )

    def _event(
        self,
        event_type: str,
        *,
        payment_id: UUID | None = None,
        business_id: UUID | None = None,
        actor: User | None = None,
        **detail,
    ) -> None:
        """Add an audit event to the current database transaction."""
        self.db.add(
            PaymentEvent(
                payment_id=payment_id,
                business_id=business_id,
                actor_user_id=actor.user_id if actor else None,
                event_type=event_type,
                detail={key: str(value) for key, value in detail.items()},
            )
        )

    def _notify(
        self,
        business_id: UUID,
        event: NotificationEvent,
        enquiry_id: UUID,
    ) -> None:
        for business_user in repo.business_users(self.db, business_id):
            self.db.add(
                Notification(
                    user_id=business_user.user_id,
                    event_type=event,
                    enquiry_id=enquiry_id,
                )
            )

    def _flag_review(
        self,
        payment: Payment,
        reason: str,
    ) -> None:
        payment.needs_review = True
        payment.review_reason = reason[:200]
        self._event(
            "PAYMENT_NEEDS_REVIEW",
            payment_id=payment.payment_id,
            reason=reason,
        )

    def initiate_payment(
        self,
        actor: User,
        enquiry_id: UUID,
        phone_number: str,
    ) -> Payment:
        enquiry = repo.get_enquiry(self.db, enquiry_id)

        self._require(
            actor,
            enquiry,
            {"buyer"},
        )

        for old_payment in repo.pending_for_enquiry(self.db, enquiry_id):
            self.reconcile_payment(old_payment.payment_id)

        enquiry = repo.get_enquiry(
            self.db,
            enquiry_id,
            lock=True,
        )

        try:
            normalized_phone = normalize_msisdn(phone_number)

            self._check_can_pay(
                actor,
                enquiry,
                normalized_phone,
            )

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
            "Payment created payment_id=%s enquiry_id=%s payer=%s",
            payment.payment_id,
            enquiry_id,
            _mask(normalized_phone),
        )

        self._send_request_to_pay(payment.payment_id)

        return repo.get_payment(self.db, payment.payment_id)

    def _registered_phones(
        self,
        actor: User,
        buyer,
    ) -> set[str]:
        registered = set()
        for raw_phone in (
            getattr(actor, "phone", None),
            getattr(buyer, "contact_phone", None),
        ):
            if not raw_phone:
                continue
            try:
                registered.add(normalize_msisdn(raw_phone))
            except ValueError:
                continue
        return registered

    def _check_can_pay(
        self,
        actor: User,
        enquiry,
        normalized_phone: str,
    ) -> None:
        if enquiry is None:
            raise PaymentError(404, *_NOT_FOUND)

        if enquiry.status != EnquiryStatus.AGREED:
            raise PaymentError(
                409,
                "enquiry_not_payable",
                "The seller must accept the enquiry before you can pay",
            )

        buyer = repo.get_business(self.db, enquiry.buyer_business_id)
        seller = repo.get_business(self.db, enquiry.seller_business_id)

        if buyer is None or seller is None:
            raise PaymentError(
                404,
                "business_not_found",
                "Buyer or seller business could not be found",
            )

        if buyer.approval_status != ApprovalStatus.APPROVED:
            raise PaymentError(
                403,
                "business_not_approved",
                "Your business is not approved",
            )

        if seller.approval_status != ApprovalStatus.APPROVED:
            raise PaymentError(
                409,
                "seller_unavailable",
                "The seller cannot receive payments now",
            )

        if not (seller.payout_phone and seller.payout_network):
            raise PaymentError(
                409,
                "seller_payout_not_configured",
                "The seller has not set up payout details yet",
            )

        if (
            self.s.require_registered_payer_phone
            and normalized_phone not in self._registered_phones(actor, buyer)
        ):
            raise PaymentError(
                422,
                "payer_phone_not_registered",
                "Pay from the phone number saved on your profile, or update your profile",
            )

        amount: Decimal = Decimal(str(enquiry.total_amount))
        if amount <= 0 or amount != amount.to_integral_value():
            raise PaymentError(
                409,
                "invalid_amount",
                "This enquiry has an invalid total",
            )

        listing = repo.get_listing(self.db, enquiry.listing_id)
        if listing is None or listing.quantity < enquiry.quantity:
            raise PaymentError(
                409,
                "quantity_unavailable",
                "The seller no longer has enough stock",
            )

        if (
            repo.count_attempts_for_enquiry(self.db, enquiry.enquiry_id)
            >= self.s.max_attempts_per_enquiry
        ):
            raise PaymentError(
                429,
                "too_many_attempts",
                "Too many payment attempts for this enquiry",
            )

    def _send_request_to_pay(
        self,
        payment_id: UUID,
    ) -> None:
        payment = repo.get_payment(self.db, payment_id)
        if payment is None or payment.status != PaymentStatus.PENDING:
            return

        if getattr(payment, "mpesa_checkout_request_id", None):
            return

        enquiry = repo.get_enquiry(self.db, payment.enquiry_id)
        if enquiry is None:
            self._flag_review(payment, "Enquiry not found while sending STK Push")
            self.db.commit()
            return

        try:
            checkout_request_id = self.mpesa.request_to_pay(
                reference_id=payment.reference_id,
                amount=payment.amount,
                phone_number=payment.phone_number,
                account_reference=f"ENQ-{str(enquiry.enquiry_id)[:8].upper()}",
                transaction_desc="Athena Payment",
            )

            if not checkout_request_id:
                self._flag_review(
                    payment,
                    "Safaricom did not return a CheckoutRequestID",
                )
                self.db.commit()
                return

            payment.mpesa_checkout_request_id = str(checkout_request_id)
            self._event(
                "STK_PUSH_REQUESTED",
                payment_id=payment.payment_id,
                checkout_request_id=checkout_request_id,
            )
            self.db.commit()

        except MpesaRejected as exc:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = safe_reason(exc.reason)
            self._event(
                "PAYMENT_GATEWAY_REJECTED",
                payment_id=payment.payment_id,
                reason=exc.reason,
            )
            self.db.commit()

        except MpesaTransient as exc:
            log.warning(
                "Ambiguous STK Push result payment_id=%s error=%s",
                payment_id,
                exc,
            )
            self._flag_review(
                payment,
                "STK Push result was uncertain. Check Safaricom before attempting another payment.",
            )
            self.db.commit()

    def _lock_if_pending(self, payment: Payment) -> bool:
        """Re-read the payment under a row lock; True if it is still PENDING.

        The M-Pesa callback and a status check can race for the same payment.
        Whoever takes the lock second sees the other's result and stops, so a
        payment is settled (and stock deducted) only once.
        """
        self.db.flush()  # keep this request's unsaved changes across the re-read
        repo.get_payment(self.db, payment.payment_id, lock=True)
        return payment.status == PaymentStatus.PENDING

    def _settle_successful_payment(
        self,
        payment: Payment,
        receipt: str,
        received_amount: Decimal,
        *,
        receipt_is_real: bool = True,
        recovering: bool = False,
    ) -> None:
        """Mark payment successful, record audit event, and deduct listing stock.

        recovering: Safaricom confirmed a payment we had marked FAILED.
        """
        settleable = self._lock_if_pending(payment) or (
            recovering
            and payment.status in (PaymentStatus.FAILED, PaymentStatus.CANCELLED)
        )
        other = repo.successful_payment_for_enquiry(self.db, payment.enquiry_id)
        if settleable and other is not None and other.payment_id != payment.payment_id:
            self._flag_review(
                payment,
                f"Enquiry already paid by another attempt. Refund M-Pesa receipt {receipt}.",
            )
            self.db.commit()
            return
        if not settleable:
            # Already settled by the other path. Keep the real M-Pesa receipt if
            # the first settle only had the checkout request ID.
            if (
                receipt_is_real
                and payment.status == PaymentStatus.SUCCESSFUL
                and payment.mpesa_receipt_number
                == getattr(payment, "mpesa_checkout_request_id", None)
            ):
                payment.mpesa_receipt_number = str(receipt)
            self.db.commit()
            return

        payment.mpesa_receipt_number = str(receipt)
        payment.status = PaymentStatus.SUCCESSFUL
        payment.paid_at = _now()
        payment.failure_reason = None

        self._event(
            "PAYMENT_SETTLED",
            payment_id=payment.payment_id,
            receipt=receipt,
            amount=received_amount,
        )

        if not payment.stock_deducted:
            enquiry = repo.get_enquiry(
                self.db,
                payment.enquiry_id,
                lock=True,
            )
            if enquiry is None:
                self._flag_review(
                    payment,
                    "Payment succeeded but its enquiry could not be found",
                )
            elif enquiry.status not in (EnquiryStatus.AGREED, EnquiryStatus.PAID):
                self._flag_review(
                    payment,
                    f"Payment arrived for an enquiry that is "
                    f"{enquiry.status.value.lower()}. Refund M-Pesa receipt {receipt}.",
                )
            else:
                if enquiry.status == EnquiryStatus.AGREED:
                    enquiry.status = EnquiryStatus.PAID
                listing = repo.get_listing(self.db, enquiry.listing_id)
                if listing is None:
                    self._flag_review(
                        payment,
                        "Payment succeeded but its listing could not be found",
                    )
                elif listing.quantity < enquiry.quantity:
                    self._flag_review(
                        payment,
                        "Payment succeeded but there is insufficient stock to fulfil the enquiry",
                    )
                else:
                    listing.quantity -= enquiry.quantity
                    payment.stock_deducted = True

        self.db.commit()

    def reconcile_payment(
        self,
        payment_id: UUID,
    ) -> Payment | None:
        """
        Query the existing STK Push request status.
        If Safaricom confirms success, settle the payment and deduct stock.
        """
        payment = repo.get_payment(self.db, payment_id)
        if payment is None or payment.status != PaymentStatus.PENDING:
            return payment

        checkout_id = getattr(payment, "mpesa_checkout_request_id", None)
        if not checkout_id:
            return payment

        now = time.monotonic()
        with _POLL_LOCK:
            last_poll = _LAST_POLL.get(payment_id, 0)
            if now - last_poll < self.s.status_poll_min_interval_seconds:
                return payment
            _LAST_POLL[payment_id] = now

        try:
            result = self.mpesa.get_request_to_pay(str(checkout_id))
            if result is None:
                return payment

            if result.status == "FAILED":
                if not self._lock_if_pending(payment):
                    self.db.commit()
                    return payment
                payment.status = PaymentStatus.FAILED
                payment.failure_reason = safe_reason(result.reason)
                self._event(
                    "PAYMENT_FAILED",
                    payment_id=payment.payment_id,
                    reason=(result.reason or "Safaricom reported failure"),
                )
                self.db.commit()

            elif result.status == "SUCCESSFUL":
                # The STK query does not return the M-Pesa receipt number, so
                # store the checkout ID until (if ever) the callback brings it.
                receipt = getattr(result, "receipt", None)
                self._settle_successful_payment(
                    payment=payment,
                    receipt=receipt or str(checkout_id),
                    received_amount=payment.amount,
                    receipt_is_real=bool(receipt),
                )

            return payment

        except MpesaTransient as exc:
            log.warning(
                "M-Pesa status query failed payment_id=%s error=%s",
                payment_id,
                exc,
            )
            return payment

    @staticmethod
    def _callback_metadata(callback: dict) -> dict:
        metadata = callback.get("CallbackMetadata") or {}
        items = metadata.get("Item") or []
        extracted = {}
        for item in items:
            name = item.get("Name")
            if name:
                extracted[name] = item.get("Value")
        return extracted

    def _handle_disbursement_callback(
        self,
        reference_id: str,
        token: str,
        payload: dict,
    ) -> None:
        """Process an asynchronous Safaricom Daraja B2C disbursement callback."""
        callback_secret = self.s.callback_secret.get_secret_value()
        if not callback_secret:
            log.error("M-Pesa callback secret is not configured")
            raise PaymentError(
                500,
                "callback_configuration_error",
                "Callback verification is not configured",
            )

        if not verify_callback_token(
            callback_secret,
            "disbursement",
            reference_id,
            token,
        ):
            log.warning(
                "Invalid M-Pesa B2C callback token reference_id=%s",
                reference_id,
            )
            raise PaymentError(
                403,
                "invalid_callback_token",
                "Invalid callback token",
            )

        payment = None
        try:
            payment_uuid = UUID(reference_id)
            payment = (
                self.db.query(Payment)
                .filter(Payment.payment_id == payment_uuid)
                .with_for_update()
                .first()
            )
        except (ValueError, TypeError):
            pass

        if payment is None:
            payment = (
                self.db.query(Payment)
                .filter(Payment.payout_reference == reference_id)
                .with_for_update()
                .first()
            )

        if payment is None:
            raise PaymentError(404, *_NOT_FOUND)

        result = (payload or {}).get("Result", {})
        if not result:
            raise PaymentError(
                400,
                "invalid_callback",
                "Invalid Daraja B2C callback body",
            )

        result_code = result.get("ResultCode")
        result_desc = result.get("ResultDesc") or ""
        conversation_id = result.get("ConversationID")
        transaction_id = result.get("TransactionID")

        if result_code is None:
            raise PaymentError(
                400,
                "invalid_callback",
                "Missing ResultCode in B2C callback",
            )

        # Success is 0; failures may be numeric (e.g. 2001) or text such as
        # "SFC_IC0003", so treat anything other than 0 as a failed payout.
        result_code = str(result_code).strip()
        succeeded = result_code.lstrip("0") == "" and result_code != ""

        if payment.payout_status == PayoutStatus.PAID:
            self.db.commit()
            return

        if succeeded:
            payment.payout_status = PayoutStatus.PAID
            payment.paid_out_at = _now()
            payment.payout_failure_reason = None
            if conversation_id and not payment.payout_reference:
                payment.payout_reference = str(conversation_id)

            self._event(
                "PAYOUT_PAID",
                payment_id=payment.payment_id,
                conversation_id=conversation_id,
                transaction_id=transaction_id,
            )
        else:
            payment.payout_status = PayoutStatus.FAILED
            payment.payout_failure_reason = (
                f"{result_code}: {result_desc}" if result_desc else result_code
            )[:100]

            self._event(
                "PAYOUT_FAILED",
                payment_id=payment.payment_id,
                result_code=result_code,
                reason=result_desc,
            )

        self.db.commit()

    def handle_raw_callback(
        self,
        kind: str,
        reference_id: str,
        token: str,
        raw_body: bytes,
    ) -> None:
        """Parse a callback request body, then process it.

        An empty body is Safaricom's reachability ping and is accepted.
        """
        payload: object = {}
        if raw_body and raw_body.strip():
            try:
                payload = json.loads(raw_body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise PaymentError(
                    400, "invalid_callback", "Invalid callback JSON"
                ) from None
        if not isinstance(payload, dict):
            raise PaymentError(400, "invalid_callback", "Invalid callback payload")
        self.handle_callback(kind, reference_id, token, payload)

    def handle_callback(
        self,
        kind: str,
        reference_id: str,
        token: str,
        payload: dict | None,
    ) -> None:
        """
        Process a Safaricom Daraja callback.
        Supports both 'collection' (STK Push) and 'disbursement' (B2C).
        """
        payload = payload or {}

        if kind == "disbursement":
            return self._handle_disbursement_callback(reference_id, token, payload)

        if kind != "collection":
            raise PaymentError(
                400,
                "unsupported_callback",
                "Unsupported M-Pesa callback type",
            )

        callback_secret = self.s.callback_secret.get_secret_value()
        if not callback_secret:
            log.error("M-Pesa callback secret is not configured")
            raise PaymentError(
                500,
                "callback_configuration_error",
                "Callback verification is not configured",
            )

        if not verify_callback_token(
            callback_secret,
            kind,
            reference_id,
            token,
        ):
            log.warning(
                "Invalid M-Pesa callback token reference_id=%s",
                reference_id,
            )
            raise PaymentError(
                403,
                "invalid_callback_token",
                "Invalid callback token",
            )

        payment = (
            self.db.query(Payment)
            .filter(Payment.reference_id == reference_id)
            .with_for_update()
            .first()
        )

        if payment is None:
            raise PaymentError(404, *_NOT_FOUND)

        if not payload:
            return

        callback = payload.get("Body", {}).get("stkCallback", {})
        if not callback:
            raise PaymentError(
                400,
                "invalid_callback",
                "Invalid Daraja STK callback body",
            )

        checkout_request_id = callback.get("CheckoutRequestID")
        merchant_request_id = callback.get("MerchantRequestID")
        result_code = callback.get("ResultCode")
        result_description = callback.get("ResultDesc") or ""

        if checkout_request_id is None or result_code is None:
            raise PaymentError(
                400,
                "invalid_callback",
                "Callback is missing required transaction fields",
            )

        if merchant_request_id:
            payment.mpesa_merchant_request_id = str(merchant_request_id)

        stored_checkout_id = getattr(payment, "mpesa_checkout_request_id", None)
        if not stored_checkout_id:
            payment.mpesa_checkout_request_id = str(checkout_request_id)
            stored_checkout_id = str(checkout_request_id)

        if str(stored_checkout_id) != str(checkout_request_id):
            self._flag_review(
                payment,
                "Callback CheckoutRequestID does not match payment",
            )
            self.db.commit()
            raise PaymentError(
                409,
                "checkout_id_mismatch",
                "Callback does not match this payment",
            )

        if payment.status == PaymentStatus.SUCCESSFUL:
            # A status check may have settled it first without the receipt.
            late_receipt = self._callback_metadata(callback).get("MpesaReceiptNumber")
            if late_receipt and payment.mpesa_receipt_number == getattr(
                payment, "mpesa_checkout_request_id", None
            ):
                payment.mpesa_receipt_number = str(late_receipt)
            self.db.commit()
            return

        recovering = False
        if payment.status in (PaymentStatus.FAILED, PaymentStatus.CANCELLED):
            if str(result_code).strip() != "0":
                self._event(
                    "LATE_CALLBACK_FAILED",
                    payment_id=payment.payment_id,
                    result_code=result_code,
                    reason=result_description,
                )
                self.db.commit()
                return
            # Safaricom says the buyer paid after we had marked this failed
            # (e.g. a status check gave up too early). The money is real, so
            # record it rather than drop it.
            receipt = self._callback_metadata(callback).get("MpesaReceiptNumber")
            if repo.successful_payment_for_enquiry(self.db, payment.enquiry_id):
                self._flag_review(
                    payment,
                    f"Paid after being marked failed, but the enquiry was already "
                    f"paid by another attempt. Refund M-Pesa receipt {receipt}.",
                )
                self.db.commit()
                return
            self._event(
                "PAYMENT_RECOVERED",
                payment_id=payment.payment_id,
                previous_status=payment.status,
                previous_reason=payment.failure_reason,
                receipt=receipt,
            )
            recovering = True

        try:
            result_code_int = int(result_code)
        except (TypeError, ValueError):
            self._flag_review(
                payment,
                "Callback contains an invalid ResultCode",
            )
            self.db.commit()
            return

        if result_code_int != 0:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = safe_reason(
                result_description or "M-Pesa transaction failed"
            )
            self._event(
                "PAYMENT_FAILED",
                payment_id=payment.payment_id,
                result_code=result_code_int,
                reason=result_description,
            )
            self.db.commit()
            return

        metadata = self._callback_metadata(callback)
        receipt = metadata.get("MpesaReceiptNumber")
        callback_amount = metadata.get("Amount")
        callback_phone = metadata.get("PhoneNumber")

        if not receipt:
            self._flag_review(
                payment,
                "Successful callback did not include an M-Pesa receipt",
            )
            self.db.commit()
            return

        try:
            received_amount = Decimal(str(callback_amount))
            expected_amount = Decimal(str(payment.amount))
        except Exception:
            self._flag_review(
                payment,
                "Callback amount is missing or invalid",
            )
            self.db.commit()
            return

        if received_amount != expected_amount:
            self._flag_review(
                payment,
                "Callback amount does not match the expected payment amount",
            )
            self.db.commit()
            return

        if callback_phone is not None:
            try:
                normalized_callback_phone = normalize_msisdn(str(callback_phone))
                normalized_payment_phone = normalize_msisdn(payment.phone_number)
            except ValueError:
                self._flag_review(
                    payment,
                    "Callback contains an invalid payer phone number",
                )
                self.db.commit()
                return

            if normalized_callback_phone != normalized_payment_phone:
                self._flag_review(
                    payment,
                    "Callback phone number does not match the payer",
                )
                self.db.commit()
                return

        self._settle_successful_payment(
            payment=payment,
            receipt=str(receipt),
            received_amount=received_amount,
            recovering=recovering,
        )

        log.info(
            "M-Pesa payment callback processed payment_id=%s receipt=%s",
            payment.payment_id,
            receipt,
        )

    def get_payout_details(
        self,
        actor: User,
    ) -> dict:
        if actor.business_id is None:
            raise PaymentError(404, *_NOT_FOUND)

        business = repo.get_business(self.db, actor.business_id)
        if not business or not business.payout_phone:
            raise PaymentError(
                404,
                "payout_not_found",
                "Payout details not found",
            )

        return {
            "payout_phone": _mask(business.payout_phone),
            "payout_network": getattr(business, "payout_network", None),
        }

    def set_payout_details(
        self,
        actor: User,
        payout_phone: str,
        payout_network: str | None = None,
    ) -> dict:
        if actor.business_id is None:
            raise PaymentError(404, *_NOT_FOUND)

        business = repo.get_business(self.db, actor.business_id)
        if not business:
            raise PaymentError(
                404,
                "business_not_found",
                "Business not found",
            )

        normalized = normalize_msisdn(payout_phone)
        business.payout_phone = normalized
        if payout_network:
            business.payout_network = payout_network

        self.db.commit()

        return {
            "payout_phone": _mask(normalized),
            "payout_network": getattr(business, "payout_network", None),
        }

    def get_payment_for_actor(
        self,
        actor: User,
        payment_id: UUID,
    ) -> tuple[Payment, str]:
        payment = repo.get_payment(self.db, payment_id)
        if not payment:
            raise PaymentError(404, *_NOT_FOUND)

        enquiry = repo.get_enquiry(self.db, payment.enquiry_id)
        side = self._require(
            actor,
            enquiry,
            {"buyer", "seller", "admin"},
        )
        return self._refresh_if_pending(payment), side

    def _refresh_if_pending(self, payment: Payment) -> Payment:
        """Ask Safaricom for the result of a PENDING payment.

        The callback is the normal path, but if it never arrives (tunnel down,
        Safaricom hiccup) reading the payment still moves it on. Polling is
        rate-limited inside reconcile_payment.
        """
        if payment.status != PaymentStatus.PENDING or self.mpesa is None:
            return payment
        try:
            return self.reconcile_payment(payment.payment_id) or payment
        except MpesaError as exc:
            log.warning(
                "M-Pesa status refresh failed payment_id=%s error=%s",
                payment.payment_id,
                exc,
            )
            self.db.rollback()
            return repo.get_payment(self.db, payment.payment_id) or payment

    def get_payment_for_enquiry(
        self,
        actor: User,
        enquiry_id: UUID,
    ) -> tuple[Payment, str]:
        enquiry = repo.get_enquiry(self.db, enquiry_id)
        side = self._require(
            actor,
            enquiry,
            {"buyer", "seller", "admin"},
        )

        payment = repo.get_payment_by_enquiry_id(self.db, enquiry_id)
        if not payment:
            raise PaymentError(404, *_NOT_FOUND)

        return self._refresh_if_pending(payment), side

    def list_my_payments(
        self,
        actor: User,
        side: str | None,
        payment_status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Payment], str]:
        """Payments for the actor; with no side given, suppliers see seller-side."""
        if side is None:
            business = actor.business
            is_supplier = (
                business is not None and business.business_role == BusinessRole.SUPPLIER
            )
            side = "seller" if is_supplier else "buyer"
        return self.my_payments(actor, side, payment_status, limit, offset), side

    def my_payments(
        self,
        actor: User,
        side: str,
        payment_status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Payment]:
        if actor.user_role == UserRole.ADMIN:
            return repo.list_payments(
                self.db,
                payment_status=payment_status,
                limit=limit,
                offset=offset,
            )

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

    def confirm_receipt(
        self,
        actor: User,
        enquiry_id: UUID,
    ) -> Payment:
        enquiry = repo.get_enquiry(self.db, enquiry_id)
        self._require(
            actor,
            enquiry,
            {"buyer"},
        )

        payment = repo.get_payment_by_enquiry_id(self.db, enquiry_id)
        if not payment:
            raise PaymentError(404, *_NOT_FOUND)

        if payment.status != PaymentStatus.SUCCESSFUL:
            raise PaymentError(
                409,
                "payment_not_successful",
                "The payment has not been confirmed as successful",
            )

        if payment.payout_status != PayoutStatus.NOT_DUE:
            raise PaymentError(
                409,
                "receipt_already_confirmed",
                "Receipt has already been confirmed for this enquiry",
            )

        enquiry = repo.get_enquiry(self.db, enquiry_id, lock=True)
        now = _now()
        enquiry.status = EnquiryStatus.COMPLETED
        enquiry.closed_at = now
        payment.payout_status = PayoutStatus.PENDING
        self._event(
            "RECEIPT_CONFIRMED",
            payment_id=payment.payment_id,
            business_id=enquiry.buyer_business_id,
            actor=actor,
        )
        self.db.commit()

        if self.s.auto_payout:
            try:
                self._send_payout(payment, enquiry)
            except PaymentError as exc:
                # The buyer's confirmation stands; an admin can retry the payout
                # with POST /admin/payments/{payment_id}/payout.
                log.warning(
                    "Automatic payout not sent payment_id=%s reason=%s",
                    payment.payment_id,
                    exc.detail,
                )

        return repo.get_payment(self.db, payment.payment_id)

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

    def sweep(
        self,
        actor: User,
    ) -> dict:
        self._require_admin(actor)
        count = 0
        for payment in repo.list_pending_payments(self.db):
            self.reconcile_payment(payment.payment_id)
            count += 1
        return {"checked": count}

    def admin_reconcile(
        self,
        actor: User,
        payment_id: UUID,
    ) -> Payment:
        self._require_admin(actor)
        payment = self.reconcile_payment(payment_id)
        if payment is None:
            raise PaymentError(404, *_NOT_FOUND)
        return payment

    def admin_events(
        self,
        actor: User,
        payment_id: UUID,
    ) -> list[PaymentEvent]:
        self._require_admin(actor)
        payment = repo.get_payment(self.db, payment_id)
        if not payment:
            raise PaymentError(404, *_NOT_FOUND)
        return repo.list_payment_events(self.db, payment_id)

    def refund_payment(
        self,
        actor: User,
        payment_id: UUID,
        failure_reason: str | None,
    ) -> Payment:
        self._require_admin(actor)
        payment = repo.get_payment(self.db, payment_id)
        if not payment:
            raise PaymentError(404, *_NOT_FOUND)

        raise PaymentError(
            501,
            "refund_not_implemented",
            "M-Pesa reversal has not been implemented. The payment has not been refunded.",
        )

    def initiate_payout(
        self,
        actor: User,
        payment_id: UUID,
    ) -> Payment:
        self._require_admin(actor)

        payment = repo.get_payment(self.db, payment_id)
        if not payment:
            raise PaymentError(404, *_NOT_FOUND)

        if payment.status != PaymentStatus.SUCCESSFUL:
            raise PaymentError(
                409,
                "payment_not_successful",
                "Cannot initiate payout for a payment that is not successful",
            )

        enquiry = repo.get_enquiry(self.db, payment.enquiry_id)
        if not enquiry:
            raise PaymentError(404, *_NOT_FOUND)

        return self._send_payout(payment, enquiry)

    def _send_payout(self, payment: Payment, enquiry) -> Payment:
        """Send the seller's share by M-Pesa B2C. The result arrives by callback."""
        if payment.payout_status == PayoutStatus.PAID:
            raise PaymentError(
                409,
                "payout_already_completed",
                "This payment has already been paid out to the seller",
            )

        if payment.payout_status == PayoutStatus.PENDING and payment.payout_reference:
            raise PaymentError(
                409,
                "payout_in_progress",
                "A payout for this payment is already in progress",
            )

        seller = repo.get_business(self.db, enquiry.seller_business_id)
        if not seller or not seller.payout_phone:
            raise PaymentError(
                409,
                "seller_payout_not_configured",
                "The seller has not set up payout details yet",
            )

        payout_amount = payment.payout_amount
        if payout_amount is None:
            payout_amount = payment.amount - (payment.fee_amount or Decimal("0.00"))

        amount = Decimal(str(payout_amount))

        try:
            conversation_id = self.mpesa.transfer(
                reference_id=str(payment.payment_id),
                amount=amount,
                phone_number=seller.payout_phone,
                remarks=f"Payout {str(payment.payment_id)[:8]}",
            )

            payment.payout_reference = conversation_id
            payment.payout_status = PayoutStatus.PENDING
            payment.payout_failure_reason = None
            self._event(
                "PAYOUT_REQUESTED",
                payment_id=payment.payment_id,
                business_id=enquiry.seller_business_id,
                amount=amount,
                phone=_mask(seller.payout_phone),
            )
            self.db.commit()
            return payment

        except MpesaRejected as e:
            payment.payout_status = PayoutStatus.FAILED
            payment.payout_failure_reason = str(e.reason or e)[:100]
            self._event(
                "PAYOUT_FAILED",
                payment_id=payment.payment_id,
                reason=e.reason or e,
            )
            self.db.commit()
            raise PaymentError(400, "payout_rejected", str(e.reason or e))
        except MpesaTransient:
            self.db.rollback()
            raise PaymentError(
                503, "mpesa_unavailable", "Safaricom service unavailable"
            )
