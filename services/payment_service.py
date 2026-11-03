
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
from models.business import ApprovalStatus
from models.enquiry import EnquiryStatus
from models.notification import NotificationEvent
from models.payment import PaymentStatus, PayoutStatus, RefundStatus
from models.user import User, UserRole
from repositories import payment_repository as repo
from schemas.payment import normalize_msisdn, safe_reason
from services.mpesa import (
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

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Audit events and notifications
    # ------------------------------------------------------------------

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
                detail={
                    key: str(value)
                    for key, value in detail.items()
                },
            )
        )

    def _notify(
        self,
        business_id: UUID,
        event: NotificationEvent,
        enquiry_id: UUID,
    ) -> None:
        for business_user in repo.business_users(
            self.db,
            business_id,
        ):
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
        payment.review_reason = safe_reason(reason)

        self._event(
            "PAYMENT_NEEDS_REVIEW",
            payment_id=payment.payment_id,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Buyer: initiate payment
    # ------------------------------------------------------------------

    def initiate_payment(
        self,
        actor: User,
        enquiry_id: UUID,
        phone_number: str,
    ) -> Payment:
        enquiry = repo.get_enquiry(
            self.db,
            enquiry_id,
        )

        # TEMPORARY DEBUGGING
        print(
            "DEBUG enquiry found:",
            enquiry is not None,
        )
        print(
            "DEBUG actor user_id:",
            actor.user_id,
        )
        print(
            "DEBUG actor business_id:",
            actor.business_id,
        )

        if enquiry is not None:
            print(
                "DEBUG buyer business_id:",
                enquiry.buyer_business_id,
            )
            print(
                "DEBUG seller business_id:",
                enquiry.seller_business_id,
            )

        print(
            "DEBUG side:",
            self._side(actor, enquiry),
        )

        self._require(
            actor,
            enquiry,
            {"buyer"},
        )

      
        for old_payment in repo.pending_for_enquiry(
            self.db,
            enquiry_id,
        ):
            self.reconcile_payment(old_payment.payment_id)

        enquiry = repo.get_enquiry(
            self.db,
            enquiry_id,
            lock=True,
        )

        try:
            normalized_phone = normalize_msisdn(
                phone_number
            )

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

        self._send_request_to_pay(
            payment.payment_id,
        )

        return repo.get_payment(
            self.db,
            payment.payment_id,
        )

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
                registered.add(
                    normalize_msisdn(raw_phone)
                )
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

        buyer = repo.get_business(
            self.db,
            enquiry.buyer_business_id,
        )

        seller = repo.get_business(
            self.db,
            enquiry.seller_business_id,
        )

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

        if not (
            seller.payout_phone
            and seller.payout_network
        ):
            raise PaymentError(
                409,
                "seller_payout_not_configured",
                "The seller has not set up payout details yet",
            )

        if (
            self.s.require_registered_payer_phone
            and normalized_phone
            not in self._registered_phones(actor, buyer)
        ):
            raise PaymentError(
                422,
                "payer_phone_not_registered",
                "Pay from the phone number saved on your profile, "
                "or update your profile",
            )

        amount: Decimal = Decimal(
            str(enquiry.total_amount)
        )

        if (
            amount <= 0
            or amount != amount.to_integral_value()
        ):
            raise PaymentError(
                409,
                "invalid_amount",
                "This enquiry has an invalid total",
            )

        listing = repo.get_listing(
            self.db,
            enquiry.listing_id,
        )

        if (
            listing is None
            or listing.quantity < enquiry.quantity
        ):
            raise PaymentError(
                409,
                "quantity_unavailable",
                "The seller no longer has enough stock",
            )

        if (
            repo.count_attempts_for_enquiry(
                self.db,
                enquiry.enquiry_id,
            )
            >= self.s.max_attempts_per_enquiry
        ):
            raise PaymentError(
                429,
                "too_many_attempts",
                "Too many payment attempts for this enquiry",
            )

    # ------------------------------------------------------------------
    # Safaricom STK Push
    # ------------------------------------------------------------------

    def _send_request_to_pay(
        self,
        payment_id: UUID,
    ) -> None:
        """
        Send an STK Push request once.

        The returned CheckoutRequestID is NOT an M-Pesa receipt number.
        """

        payment = repo.get_payment(
            self.db,
            payment_id,
        )

        if payment is None:
            return

        if payment.status != PaymentStatus.PENDING:
            return
        if getattr(
            payment,
            "mpesa_checkout_request_id",
            None,
        ):
            return

        enquiry = repo.get_enquiry(
            self.db,
            payment.enquiry_id,
        )

        if enquiry is None:
            self._flag_review(
                payment,
                "Enquiry not found while sending STK Push",
            )
            self.db.commit()
            return

        try:
            checkout_request_id = self.mpesa.request_to_pay(
                reference_id=payment.reference_id,
                amount=payment.amount,
                phone_number=payment.phone_number,
                account_reference=(
                    f"ENQ-{str(enquiry.enquiry_id)[:8].upper()}"
                ),
                transaction_desc="Athena Payment",
            )

            if not checkout_request_id:
                self._flag_review(
                    payment,
                    "Safaricom did not return a CheckoutRequestID",
                )
                self.db.commit()
                return

            payment.mpesa_checkout_request_id = str(
                checkout_request_id
            )

            self._event(
                "STK_PUSH_REQUESTED",
                payment_id=payment.payment_id,
                checkout_request_id=checkout_request_id,
            )

            self.db.commit()

        except MpesaRejected as exc:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = safe_reason(
                exc.reason
            )

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
                "STK Push result was uncertain. Check Safaricom "
                "before attempting another payment.",
            )

            self.db.commit()

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def reconcile_payment(
        self,
        payment_id: UUID,
    ) -> Payment | None:
        """
        Query the existing STK Push request.

        This method deliberately does not create a new STK Push request.
        A successful query response alone is not used to mark a payment
        settled because the actual receipt metadata should come from
        the callback.
        """

        payment = repo.get_payment(
            self.db,
            payment_id,
        )

        if (
            payment is None
            or payment.status != PaymentStatus.PENDING
        ):
            return payment

        checkout_id = getattr(
            payment,
            "mpesa_checkout_request_id",
            None,
        )

        if not checkout_id:
            # No CheckoutRequestID means we cannot safely query.
            # In particular, do not resend the STK Push here.
            return payment

        # Avoid excessive repeated polling in one application process.
        now = time.monotonic()

        with _POLL_LOCK:
            last_poll = _LAST_POLL.get(
                payment_id,
                0,
            )

            if (
                now - last_poll
                < self.s.status_poll_min_interval_seconds
            ):
                return payment

            _LAST_POLL[payment_id] = now

        try:
            result = self.mpesa.get_request_to_pay(
                str(checkout_id)
            )

            if result is None:
                return payment

            if result.status == "FAILED":
                payment.status = PaymentStatus.FAILED
                payment.failure_reason = safe_reason(
                    result.reason
                )

                self._event(
                    "PAYMENT_FAILED",
                    payment_id=payment.payment_id,
                    reason=(
                        result.reason
                        or "Safaricom reported failure"
                    ),
                )

                self.db.commit()

            elif result.status == "SUCCESSFUL":
                # A query result is not a receipt number.
                # Wait for the callback to supply receipt metadata.
                if not payment.needs_review:
                    self._flag_review(
                        payment,
                        "Safaricom query reports success but callback "
                        "receipt metadata has not been received.",
                    )
                    self.db.commit()

            return payment

        except MpesaTransient as exc:
            log.warning(
                "M-Pesa status query failed payment_id=%s error=%s",
                payment_id,
                exc,
            )
            return payment

    # ------------------------------------------------------------------
    # Daraja callback helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _callback_metadata(callback: dict) -> dict:
        """
        Extract values from:

        Body.stkCallback.CallbackMetadata.Item
        """

        metadata = (
            callback.get("CallbackMetadata")
            or {}
        )

        items = metadata.get("Item") or []

        extracted = {}

        for item in items:
            name = item.get("Name")

            if name:
                extracted[name] = item.get("Value")

        return extracted

    # ------------------------------------------------------------------
    # Daraja callback handler
    # ------------------------------------------------------------------


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

        result = payload.get("Result", {})
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

        try:
            result_code_int = int(result_code)
        except (TypeError, ValueError):
            self._flag_review(
                payment,
                "B2C Callback contains an invalid ResultCode",
            )
            self.db.commit()
            return

        if payment.payout_status == PayoutStatus.PAID:
            self.db.commit()
            return

        if result_code_int == 0:
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
            payment.payout_failure_reason = str(result_desc)[:100]

            self._event(
                "PAYOUT_FAILED",
                payment_id=payment.payment_id,
                result_code=result_code_int,
                reason=result_desc,
            )

        self.db.commit()

    def handle_callback(
        self,
        kind: str,
        reference_id: str,
        token: str,
        payload: dict,
    ) -> None:
        """
        Process a Safaricom Daraja callback.

        The callback URL contains our own HMAC token. Safaricom does not
        generate this token; it is used to protect the callback URL.

        The callback body is then checked against the stored payment.
        """

        if kind == "disbursement":
            return self._handle_disbursement_callback(
                reference_id, token, payload
            )

        if kind != "collection":
            raise PaymentError(
                400,
                "unsupported_callback",
                "Unsupported M-Pesa callback type",
            )

        callback_secret = (
            self.s.callback_secret.get_secret_value()
        )

        if not callback_secret:
            log.error(
                "M-Pesa callback secret is not configured"
            )

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
            .filter(
                Payment.reference_id == reference_id
            )
            .with_for_update()
            .first()
        )

        if payment is None:
            raise PaymentError(404, *_NOT_FOUND)

        callback = (
            payload.get("Body", {})
            .get("stkCallback", {})
        )

        if not callback:
            raise PaymentError(
                400,
                "invalid_callback",
                "Invalid Daraja STK callback body",
            )

        checkout_request_id = callback.get(
            "CheckoutRequestID"
        )

        merchant_request_id = callback.get(
            "MerchantRequestID"
        )

        result_code = callback.get("ResultCode")
        result_description = (
            callback.get("ResultDesc") or ""
        )

        if (
            checkout_request_id is None
            or result_code is None
        ):
            raise PaymentError(
                400,
                "invalid_callback",
                "Callback is missing required transaction fields",
            )

        if merchant_request_id:
            payment.mpesa_merchant_request_id = str(
                merchant_request_id
            )

        stored_checkout_id = getattr(
            payment,
            "mpesa_checkout_request_id",
            None,
        )

        if not stored_checkout_id:
            payment.mpesa_checkout_request_id = str(
                checkout_request_id
            )
            stored_checkout_id = str(checkout_request_id)

        if (
            str(stored_checkout_id)
            != str(checkout_request_id)
        ):
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
            self.db.commit()
            return

        if payment.status in (
            PaymentStatus.FAILED,
            PaymentStatus.CANCELLED,
        ):
            self._flag_review(
                payment,
                "A callback was received for a payment already marked "
                "failed or cancelled.",
            )
            self.db.commit()
            return

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
                result_description
                or "M-Pesa transaction failed"
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

        receipt = metadata.get(
            "MpesaReceiptNumber"
        )
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
            received_amount = Decimal(
                str(callback_amount)
            )
            expected_amount = Decimal(
                str(payment.amount)
            )
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
                normalized_callback_phone = normalize_msisdn(
                    str(callback_phone)
                )
                normalized_payment_phone = normalize_msisdn(
                    payment.phone_number
                )
            except ValueError:
                self._flag_review(
                    payment,
                    "Callback contains an invalid payer phone number",
                )
                self.db.commit()
                return

            if (
                normalized_callback_phone
                != normalized_payment_phone
            ):
                self._flag_review(
                    payment,
                    "Callback phone number does not match the payer",
                )
                self.db.commit()
                return

        # Only an actual M-Pesa receipt is stored in this field.
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
            else:
                listing = repo.get_listing(
                    self.db,
                    enquiry.listing_id,
                )

                if listing is None:
                    self._flag_review(
                        payment,
                        "Payment succeeded but its listing could not be found",
                    )

                elif listing.quantity < enquiry.quantity:
                    self._flag_review(
                        payment,
                        "Payment succeeded but there is insufficient stock "
                        "to fulfil the enquiry",
                    )

                else:
                    listing.quantity -= enquiry.quantity
                    payment.stock_deducted = True

        self.db.commit()

        log.info(
            "M-Pesa payment callback processed payment_id=%s receipt=%s",
            payment.payment_id,
            receipt,
        )

    # ------------------------------------------------------------------
    # Seller payout details
    # ------------------------------------------------------------------

    def get_payout_details(
        self,
        actor: User,
    ) -> dict:
        if actor.business_id is None:
            raise PaymentError(404, *_NOT_FOUND)

        business = repo.get_business(
            self.db,
            actor.business_id,
        )

        if not business or not business.payout_phone:
            raise PaymentError(
                404,
                "payout_not_found",
                "Payout details not found",
            )

        return {
            "payout_phone": _mask(
                business.payout_phone
            ),
            "payout_network": getattr(
                business,
                "payout_network",
                None,
            ),
        }

    def set_payout_details(
        self,
        actor: User,
        payout_phone: str,
        payout_network: str | None = None,
    ) -> dict:
        if actor.business_id is None:
            raise PaymentError(404, *_NOT_FOUND)

        business = repo.get_business(
            self.db,
            actor.business_id,
        )

        if not business:
            raise PaymentError(
                404,
                "business_not_found",
                "Business not found",
            )

        normalized = normalize_msisdn(
            payout_phone
        )

        business.payout_phone = normalized

        if payout_network:
            business.payout_network = payout_network

        self.db.commit()

        return {
            "payout_phone": _mask(normalized),
            "payout_network": getattr(
                business,
                "payout_network",
                None,
            ),
        }

    # ------------------------------------------------------------------
    # Payment reads
    # ------------------------------------------------------------------

    def get_payment_for_actor(
        self,
        actor: User,
        payment_id: UUID,
    ) -> tuple[Payment, str]:
        payment = repo.get_payment(
            self.db,
            payment_id,
        )

        if not payment:
            raise PaymentError(404, *_NOT_FOUND)

        enquiry = repo.get_enquiry(
            self.db,
            payment.enquiry_id,
        )

        side = self._require(
            actor,
            enquiry,
            {"buyer", "seller", "admin"},
        )

        return payment, side

    def get_payment_for_enquiry(
        self,
        actor: User,
        enquiry_id: UUID,
    ) -> tuple[Payment, str]:
        enquiry = repo.get_enquiry(
            self.db,
            enquiry_id,
        )

        side = self._require(
            actor,
            enquiry,
            {"buyer", "seller", "admin"},
        )

        payment = repo.get_payment_by_enquiry_id(
            self.db,
            enquiry_id,
        )

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
        enquiry = repo.get_enquiry(
            self.db,
            enquiry_id,
        )

        self._require(
            actor,
            enquiry,
            {"buyer"},
        )

        payment = repo.get_payment_by_enquiry_id(
            self.db,
            enquiry_id,
        )

        if not payment:
            raise PaymentError(404, *_NOT_FOUND)

        if payment.status != PaymentStatus.SUCCESSFUL:
            raise PaymentError(
                409,
                "payment_not_successful",
                "The payment has not been confirmed as successful",
            )


        payment.payout_status = PayoutStatus.PENDING

        self.db.commit()

        return payment

    # ------------------------------------------------------------------
    # Admin actions
    # ------------------------------------------------------------------

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

        for payment in repo.list_pending_payments(
            self.db
        ):
            self.reconcile_payment(
                payment.payment_id
            )
            count += 1

        return {"checked": count}

    def admin_reconcile(
        self,
        actor: User,
        payment_id: UUID,
    ) -> Payment | None:
        self._require_admin(actor)

        return self.reconcile_payment(
            payment_id
        )

    def admin_events(
        self,
        actor: User,
        payment_id: UUID,
    ) -> list[PaymentEvent]:
        self._require_admin(actor)

        payment = repo.get_payment(
            self.db,
            payment_id,
        )

        if not payment:
            raise PaymentError(404, *_NOT_FOUND)

        return repo.list_payment_events(
            self.db,
            payment_id,
        )

    # ------------------------------------------------------------------
    # Refunds and payouts
    # ------------------------------------------------------------------

    def refund_payment(
        self,
        actor: User,
        payment_id: UUID,
        failure_reason: str | None,
    ) -> Payment:
        self._require_admin(actor)

        payment = repo.get_payment(
            self.db,
            payment_id,
        )

        if not payment:
            raise PaymentError(404, *_NOT_FOUND)


        raise PaymentError(
            501,
            "refund_not_implemented",
            "M-Pesa reversal has not been implemented. "
            "The payment has not been refunded.",
        )

    def initiate_payout(
        self,
        actor: User,
        payment_id: UUID,
    ) -> Payment:
        self._require_admin(actor)

        payment = repo.get_payment(
            self.db,
            payment_id,
        )

        if not payment:
            raise PaymentError(404, *_NOT_FOUND)

        if payment.status != PaymentStatus.SUCCESSFUL:
            raise PaymentError(
                409,
                "payment_not_successful",
                "Cannot initiate payout for a payment that is not successful",
            )

        if payment.payout_status == PayoutStatus.PAID:
            raise PaymentError(
                409,
                "payout_already_completed",
                "This payment has already been paid out to the seller",
            )

        enquiry = repo.get_enquiry(self.db, payment.enquiry_id)
        if not enquiry:
            raise PaymentError(404, *_NOT_FOUND)

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
            self.db.commit()
            return payment

        except MpesaRejected as e:
            payment.payout_status = PayoutStatus.FAILED
            payment.payout_failure_reason = str(e.reason or e)[:100]
            self.db.commit()
            raise PaymentError(400, "payout_rejected", str(e.reason or e))
        except MpesaTransient as e:
            self.db.rollback()
            raise PaymentError(503, "mpesa_unavailable", "Safaricom service unavailable")