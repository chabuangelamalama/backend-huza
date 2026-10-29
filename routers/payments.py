"""Payment endpoints (buyer, seller, M-Pesa callback, admin)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from core.payment_config import MpesaSettings
from core.payment_deps import (
    get_current_user,
    get_db,
    get_mpesa_client,
    get_settings,
)
from models.business import BusinessRole
from models.payment import Payment
from models.user import User
from services.mpesa import MpesaGateway
from services.payment_service import PaymentService

router = APIRouter(tags=["payments"])

NO_STORE = {"Cache-Control": "no-store"}


class PaymentStartRequest(BaseModel):
    """Request to initiate a payment."""

    model_config = ConfigDict(extra="forbid")

    phone_number: str


class PayoutDetailsRequest(BaseModel):
    """Request to create or update seller payout details."""

    model_config = ConfigDict(extra="forbid")

    payout_phone: str
    payout_network: str | None = None


class RefundRequest(BaseModel):
    """Request to refund a payment."""

    model_config = ConfigDict(extra="forbid")

    failure_reason: str | None = None


# --------------------------------------------------------- service dependency


def get_service(
    db: Session = Depends(get_db),
    mpesa: MpesaGateway = Depends(get_mpesa_client),
    settings: MpesaSettings = Depends(get_settings),
) -> PaymentService:
    return PaymentService(db, mpesa, settings)


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    clean = str(phone).replace("+", "").strip()
    if len(clean) >= 6:
        return f"{clean[:3]}****{clean[-3:]}"
    return clean


def _view(payment: Payment, side: str) -> dict:
    """Return filtered payment representation according to the actor's side."""
    status_str = (
        payment.status.value
        if hasattr(payment.status, "value")
        else str(payment.status)
    )
    payout_status_str = (
        payment.payout_status.value
        if hasattr(payment.payout_status, "value")
        else str(payment.payout_status)
    )

    data = {
        "payment_id": str(payment.payment_id),
        "enquiry_id": str(payment.enquiry_id),
        "amount": float(payment.amount) if payment.amount is not None else 0.0,
        "status": status_str,
        "payout_status": payout_status_str,
    }

    if side == "buyer":
        data["phone_number"] = _mask_phone(payment.phone_number)
    elif side == "seller":
        # Seller should never see buyer phone number
        pass
    elif side == "admin":
        data["reference_id"] = payment.reference_id
        data["needs_review"] = getattr(payment, "needs_review", False)
        data["phone_number"] = payment.phone_number

    return data


# ---------------------------------------------------------------- buyer side


@router.post(
    "/enquiries/{enquiry_id}/payments",
    status_code=status.HTTP_202_ACCEPTED,
)
def pay_enquiry(
    enquiry_id: UUID,
    body: PaymentStartRequest,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    """Initiate an M-Pesa STK Push for an enquiry."""
    response.headers.update(NO_STORE)

    payment = svc.initiate_payment(
        user,
        enquiry_id,
        body.phone_number,
    )

    return _view(payment, "buyer")


@router.post("/enquiries/{enquiry_id}/confirm-receipt")
def confirm_receipt(
    enquiry_id: UUID,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    """Buyer confirms receipt of goods."""
    response.headers.update(NO_STORE)

    payment = svc.confirm_receipt(user, enquiry_id)

    return _view(payment, "buyer")


# ------------------------------------------------ seller payout details


@router.get("/payments/payout-details")
def get_payout_details(
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)

    return svc.get_payout_details(user)


@router.put("/payments/payout-details")
def set_payout_details(
    body: PayoutDetailsRequest,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)

    return svc.set_payout_details(
        user,
        body.payout_phone,
        body.payout_network,
    )


# ----------------------------------------------------- M-Pesa callback


@router.api_route(
    "/payments/mpesa/callback/{kind}/{reference_id}/{token}",
    methods=["PUT", "POST"],
    include_in_schema=False,
)
def mpesa_callback(
    kind: str,
    reference_id: str,
    token: str,
    svc: PaymentService = Depends(get_service),
):
    """Handle a callback after the service validates its signature."""
    svc.handle_callback(kind, reference_id, token)

    return Response(status_code=status.HTTP_200_OK)


# ------------------------------------------------------------------ admin


@router.get("/admin/payments")
def admin_list_payments(
    payment_status: str | None = Query(None, alias="status"),
    payout_status: str | None = None,
    needs_review: bool | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    rows = svc.admin_list(
        user,
        payment_status,
        payout_status,
        needs_review,
        limit,
        offset,
    )

    return [_view(payment, "admin") for payment in rows]


@router.post("/admin/payments/sweep")
def admin_sweep(
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    return svc.sweep(user)


@router.post("/admin/payments/{payment_id}/reconcile")
def admin_reconcile(
    payment_id: UUID,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    payment = svc.admin_reconcile(user, payment_id)

    return _view(payment, "admin")


@router.get("/admin/payments/{payment_id}/events")
def admin_events(
    payment_id: UUID,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    return svc.admin_events(user, payment_id)


@router.post("/admin/payments/{payment_id}/refund")
def admin_refund(
    payment_id: UUID,
    body: RefundRequest,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    """Refund a payment when permitted by the payment service."""
    payment = svc.refund_payment(
        user,
        payment_id,
        body.failure_reason,
    )

    return _view(payment, "admin")


@router.post("/admin/payments/{payment_id}/payout")
def admin_payout(
    payment_id: UUID,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    payment = svc.initiate_payout(user, payment_id)

    return _view(payment, "admin")


# ------------------------------------------------------------ shared reads


@router.get("/payments")
def my_payments(
    response: Response,
    side: str | None = Query(None, pattern="^(buyer|seller)$"),
    payment_status: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)

    if side is None:
        business = user.business

        is_supplier = (
            business is not None and business.business_role == BusinessRole.SUPPLIER
        )

        side = "seller" if is_supplier else "buyer"

    rows = svc.my_payments(
        user,
        side,
        payment_status,
        limit,
        offset,
    )

    return [_view(payment, side) for payment in rows]


@router.get("/payments/{payment_id}")
def get_payment(
    payment_id: UUID,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)

    payment, side = svc.get_payment_for_actor(user, payment_id)

    return _view(payment, side)


@router.get("/enquiries/{enquiry_id}/payments")
def enquiry_payments(
    enquiry_id: UUID,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)

    payment, side = svc.get_payment_for_enquiry(user, enquiry_id)

    return _view(payment, side)
