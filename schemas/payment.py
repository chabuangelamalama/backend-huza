import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.business import PayoutNetwork
from models.enquiry import FailureReason
from models.payment import Payment, PaymentStatus, PayoutStatus, RefundStatus


_MSISDN_RE = re.compile(r"^254\d{9}$")


def normalize_msisdn(raw: str) -> str:
    """'+254 712 345 678' / '0712345678' / '254712345678' -> '254712345678'."""
    digits = re.sub(r"[\s\-().]", "", raw.strip())
    if digits.startswith("+"):
        digits = digits[1:]
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    elif digits.startswith("7") and len(digits) == 9:
        digits = "254" + digits
    if not _MSISDN_RE.match(digits):
        raise ValueError("Enter a valid Safaricom M-Pesa number, e.g. 0712345678")
    return digits


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    return f"{phone[:3]}****{phone[-3:]}" if len(phone) >= 8 else "****"


FAILURE_MESSAGES = {
    "NOT_ENOUGH_FUNDS": "Your M-Pesa balance is too low for this payment.",
    "PAYER_NOT_FOUND": "That number is not registered for M-Pesa.",
    "PAYER_LIMIT_REACHED": "You have reached your M-Pesa transaction limit.",
    "APPROVAL_REJECTED": "The payment was declined on your phone.",
    "PAYMENT_NOT_APPROVED": "The payment request timed out.",
    "EXPIRED": "The payment request expired. Please try again.",
    "TRANSACTION_CANCELED": "The payment was cancelled.",
    "SERVICE_UNAVAILABLE": "M-Pesa API is unavailable. Please try again shortly.",
}
DEFAULT_FAILURE_MESSAGE = "The payment could not be completed. Please try again."
KNOWN_REASONS = set(FAILURE_MESSAGES) | {
    "PAYEE_NOT_FOUND",
    "NOT_ALLOWED",
    "INVALID_CURRENCY",
    "INTERNAL_PROCESSING_ERROR",
    "RESOURCE_NOT_FOUND",
}


def safe_reason(raw: str | None) -> str:
    """Only store known M-Pesa codes; never persist arbitrary text from outside."""
    return raw if raw in KNOWN_REASONS else "UNKNOWN"


class InitiatePaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_number: str = Field(min_length=9, max_length=20)

    @field_validator("phone_number")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_msisdn(v)


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failure_reason: FailureReason | None = None


class PayoutDetailsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payout_phone: str = Field(min_length=9, max_length=20)
    payout_network: PayoutNetwork = PayoutNetwork.MPESA

    @field_validator("payout_phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_msisdn(v)


# ---- responses ---------------------------------------------------------------
class PaymentBuyerOut(BaseModel):
    payment_id: UUID
    enquiry_id: UUID
    amount: Decimal
    status: PaymentStatus
    phone_number: str | None
    failure_message: str | None
    refund_status: RefundStatus
    paid_at: datetime | None
    created_at: datetime


class PaymentSellerOut(BaseModel):
    payment_id: UUID
    enquiry_id: UUID
    amount: Decimal
    status: PaymentStatus
    payout_status: PayoutStatus
    fee_amount: Decimal
    payout_amount: Decimal | None
    refund_status: RefundStatus
    paid_at: datetime | None
    paid_out_at: datetime | None
    created_at: datetime


class PaymentAdminOut(PaymentBuyerOut):
    reference_id: str
    mpesa_receipt_number: str | None
    failure_reason: str | None
    payout_status: PayoutStatus
    payout_reference: str | None
    payout_failure_reason: str | None
    fee_amount: Decimal
    payout_amount: Decimal | None
    paid_out_at: datetime | None
    refund_reference: str | None
    refunded_at: datetime | None
    stock_deducted: bool
    needs_review: bool
    review_reason: str | None


class PaymentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_id: UUID
    payment_id: UUID | None
    business_id: UUID | None
    actor_user_id: UUID | None
    event_type: str
    detail: dict
    created_at: datetime


class PayoutDetailsOut(BaseModel):
    payout_phone: str | None
    payout_network: PayoutNetwork | None


def buyer_view(p: Payment) -> PaymentBuyerOut:
    msg = None
    if p.status == PaymentStatus.FAILED:
        msg = FAILURE_MESSAGES.get(p.failure_reason or "", DEFAULT_FAILURE_MESSAGE)
    return PaymentBuyerOut(
        payment_id=p.payment_id,
        enquiry_id=p.enquiry_id,
        amount=p.amount,
        status=p.status,
        phone_number=mask_phone(p.phone_number),
        failure_message=msg,
        refund_status=p.refund_status,
        paid_at=p.paid_at,
        created_at=p.created_at,
    )


def seller_view(p: Payment) -> PaymentSellerOut:
    return PaymentSellerOut(
        payment_id=p.payment_id,
        enquiry_id=p.enquiry_id,
        amount=p.amount,
        status=p.status,
        payout_status=p.payout_status,
        fee_amount=p.fee_amount,
        payout_amount=p.payout_amount,
        refund_status=p.refund_status,
        paid_at=p.paid_at,
        paid_out_at=p.paid_out_at,
        created_at=p.created_at,
    )


def admin_view(p: Payment) -> PaymentAdminOut:
    base = buyer_view(p).model_dump()
    return PaymentAdminOut(
        **base,
        reference_id=p.reference_id,
        mpesa_receipt_number=p.mpesa_receipt_number,
        failure_reason=p.failure_reason,
        payout_status=p.payout_status,
        payout_reference=p.payout_reference,
        payout_failure_reason=p.payout_failure_reason,
        fee_amount=p.fee_amount,
        payout_amount=p.payout_amount,
        paid_out_at=p.paid_out_at,
        refund_reference=p.refund_reference,
        refunded_at=p.refunded_at,
        stock_deducted=p.stock_deducted,
        needs_review=p.needs_review,
        review_reason=p.review_reason,
    )
