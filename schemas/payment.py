import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.business import PayoutNetwork
from models.enquiry import FailureReason
from models.payment import Payment, PaymentStatus, PayoutStatus, RefundStatus


_MSISDN_RE = re.compile(r"^2507[89]\d{7}$")


def normalize_msisdn(raw: str) -> str:
    """'+250 788 123 456' / '0788123456' / '250788123456' -> '250788123456'."""
    digits = re.sub(r"[\s\-().]", "", raw.strip())
    if digits.startswith("+"):
        digits = digits[1:]
    if digits.startswith("0"):
        digits = "250" + digits[1:]
    if not _MSISDN_RE.match(digits):
        raise ValueError("Enter a valid MTN Rwanda number, e.g. 0788123456")
    return digits


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    return f"{phone[:3]}****{phone[-3:]}" if len(phone) >= 8 else "****"


FAILURE_MESSAGES = {
    "NOT_ENOUGH_FUNDS": "Your MoMo balance is too low for this payment.",
    "PAYER_NOT_FOUND": "That number is not registered for MTN MoMo.",
    "PAYER_LIMIT_REACHED": "You have reached your MoMo transaction limit.",
    "APPROVAL_REJECTED": "The payment was declined on your phone.",
    "PAYMENT_NOT_APPROVED": "The payment was not approved in time.",
    "EXPIRED": "The payment request expired. Please try again.",
    "TRANSACTION_CANCELED": "The payment was cancelled.",
    "SERVICE_UNAVAILABLE": "MTN MoMo is unavailable. Please try again shortly.",
}
DEFAULT_FAILURE_MESSAGE = "The payment could not be completed. Please try again."
KNOWN_REASONS = set(FAILURE_MESSAGES) | {
    "PAYEE_NOT_FOUND",
    "NOT_ALLOWED",
    "NOT_ALLOWED_TARGET_ENVIRONMENT",
    "INVALID_CALLBACK_URL_HOST",
    "INVALID_CURRENCY",
    "INTERNAL_PROCESSING_ERROR",
    "PAYEE_NOT_ALLOWED_TO_RECEIVE",
    "RESOURCE_NOT_FOUND",
    "RESOURCE_ALREADY_EXIST",
    "NOT_FOUND_AT_MTN",
}


def safe_reason(raw: str | None) -> str:
    """Only store known MTN codes; never persist arbitrary text from outside."""
    return raw if raw in KNOWN_REASONS else "UNKNOWN"


class InitiatePaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payer_phone: str = Field(min_length=9, max_length=20)

    @field_validator("payer_phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_msisdn(v)


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failure_reason: FailureReason | None = None


class PayoutDetailsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payout_phone: str = Field(min_length=9, max_length=20)
    payout_network: PayoutNetwork = PayoutNetwork.MTN_MOMO

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
    payer_phone: str | None
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
    momo_transaction_id: str | None
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
        payer_phone=mask_phone(p.payer_phone),
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
        momo_transaction_id=p.momo_transaction_id,
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
