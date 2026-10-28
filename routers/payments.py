"""Payment endpoints (buyer, seller, MTN callback, admin)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from core.payment_config import MomoSettings
from core.payment_deps import (
    get_current_user,
    get_db,
    get_momo_client,
    get_settings,
)
from models.business import BusinessRole
from models.payment import Payment, PaymentStatus, PayoutStatus
from models.user import User, UserRole
from schemas.payment import (
    InitiatePaymentRequest,
    PaymentAdminOut,
    PaymentBuyerOut,
    PaymentEventOut,
    PayoutDetailsOut,
    PayoutDetailsRequest,
    RefundRequest,
    admin_view,
    buyer_view,
    mask_phone,
    seller_view,
)
from services.momo import MomoGateway
from services.payment_service import PaymentError, PaymentService

router = APIRouter(tags=["payments"])

NO_STORE = {"Cache-Control": "no-store"}


def get_service(
    db: Session = Depends(get_db),
    momo: MomoGateway = Depends(get_momo_client),
    settings: MomoSettings = Depends(get_settings),
) -> PaymentService:
    return PaymentService(db, momo, settings)


def _view(payment: Payment, side: str):
    if side == "admin":
        return admin_view(payment)
    return seller_view(payment) if side == "seller" else buyer_view(payment)


def _ensure_admin(user: User) -> None:
    """Blocks non-admin requests from administrative routes.

    Administrators are users with user_role ADMIN. They have no business.
    """
    if user.user_role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Administrative privileges required.",
        )


# ------------------------------------------------------------------ buyer side
@router.post(
    "/enquiries/{enquiry_id}/payments",
    response_model=PaymentBuyerOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def pay_enquiry(
    enquiry_id: UUID,
    body: InitiatePaymentRequest,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    """Sends a MoMo prompt to the buyer's phone. Poll GET /payments/{id} for the result."""
    response.headers.update(NO_STORE)
    payment = svc.initiate_payment(user, enquiry_id, body.payer_phone)
    return buyer_view(payment)


@router.post(
    "/enquiries/{enquiry_id}/confirm-receipt",
    response_model=PaymentBuyerOut,
)
def confirm_receipt(
    enquiry_id: UUID,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    """Buyer confirms the goods arrived: enquiry becomes COMPLETED and the seller is paid."""
    response.headers.update(NO_STORE)
    return buyer_view(svc.confirm_receipt(user, enquiry_id))


# --------------------------------------------------- seller: payout details
# (declared BEFORE /payments/{payment_id} so "payout-details" is not parsed as a UUID)
@router.get("/payments/payout-details", response_model=PayoutDetailsOut)
def get_payout_details(
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)
    b = svc.get_payout_details(user)
    return PayoutDetailsOut(
        payout_phone=mask_phone(b.payout_phone), payout_network=b.payout_network
    )


@router.put("/payments/payout-details", response_model=PayoutDetailsOut)
def set_payout_details(
    body: PayoutDetailsRequest,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)
    b = svc.set_payout_details(user, body.payout_phone, body.payout_network)
    return PayoutDetailsOut(
        payout_phone=mask_phone(b.payout_phone), payout_network=b.payout_network
    )


# ------------------------------------------------------------- MTN callback
@router.api_route(
    "/payments/momo/callback/{kind}/{reference_id}/{token}",
    methods=["PUT", "POST"],
    include_in_schema=False,
)
def momo_callback(
    kind: str,
    reference_id: str,
    token: str,
    svc: PaymentService = Depends(get_service),
):
    """The body is ignored. We verify the signed URL, then ask MTN for the real status."""
    svc.handle_callback(kind, reference_id, token)
    return Response(status_code=status.HTTP_200_OK)


# ------------------------------------------------------------------- admin
@router.get("/admin/payments", response_model=list[PaymentAdminOut])
def admin_list_payments(
    payment_status: PaymentStatus | None = Query(None, alias="status"),
    payout_status: PayoutStatus | None = None,
    needs_review: bool | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    _ensure_admin(user)
    rows = svc.admin_list(
        user, payment_status, payout_status, needs_review, limit, offset
    )
    return [admin_view(p) for p in rows]


@router.post("/admin/payments/sweep")
def admin_sweep(
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    _ensure_admin(user)
    return svc.sweep(user)


@router.post("/admin/payments/{payment_id}/reconcile", response_model=PaymentAdminOut)
def admin_reconcile(
    payment_id: UUID,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    _ensure_admin(user)
    return admin_view(svc.admin_reconcile(user, payment_id))


@router.get(
    "/admin/payments/{payment_id}/events", response_model=list[PaymentEventOut]
)
def admin_events(
    payment_id: UUID,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    _ensure_admin(user)
    return svc.admin_events(user, payment_id)


@router.post("/admin/payments/{payment_id}/refund", response_model=PaymentAdminOut)
def admin_refund(
    payment_id: UUID,
    body: RefundRequest,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    """Return the buyer's money (only before the seller payout is sent)."""
    _ensure_admin(user)
    return admin_view(svc.refund_payment(user, payment_id, body.failure_reason))


@router.post("/admin/payments/{payment_id}/payout", response_model=PaymentAdminOut)
def admin_payout(
    payment_id: UUID,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    _ensure_admin(user)
    return admin_view(svc.initiate_payout(user, payment_id))


# ------------------------------------------------- shared reads (all parties)
# response_model=None: the view class differs per caller (buyer / seller / admin).
@router.get("/payments", response_model=None)
def my_payments(
    response: Response,
    side: str | None = Query(None, pattern="^(buyer|seller)$"),
    payment_status: PaymentStatus | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    """Your payments. Pass side=buyer or side=seller (processors do both, so they
    should choose). Without it, suppliers see their sales and everyone else their
    purchases."""
    response.headers.update(NO_STORE)
    if side is None:
        business = user.business
        is_supplier = (
            business is not None and business.business_role == BusinessRole.SUPPLIER
        )
        side = "seller" if is_supplier else "buyer"
    rows = svc.my_payments(user, side, payment_status, limit, offset)
    return [_view(p, side) for p in rows]


@router.get("/payments/{payment_id}", response_model=None)
def get_payment(
    payment_id: UUID,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)
    payment, side = svc.get_payment_for_actor(user, payment_id)
    return _view(payment, side)


@router.get("/enquiries/{enquiry_id}/payments", response_model=None)
def enquiry_payments(
    enquiry_id: UUID,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)
    rows, side = svc.payments_for_enquiry(user, enquiry_id)
    return [_view(p, side) for p in rows]


__all__ = ["router", "PaymentError"]