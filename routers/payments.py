"""Payment endpoints (buyer, seller, M-Pesa callback, admin)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from core.payment_config import MpesaSettings
from core.payment_deps import (
    get_current_user,
    get_db,
    get_mpesa_client,
    get_settings,
)
from models.business import BusinessRole
from models.payment import Payment, PaymentStatus, PayoutStatus
from models.user import User, UserRole
from services.mpesa import MpesaGateway
from services.payment_service import PaymentError, PaymentService

router = APIRouter(tags=["payments"])

NO_STORE = {"Cache-Control": "no-store"}


def get_service(
    db: Session = Depends(get_db),
    mpesa: MpesaGateway = Depends(get_mpesa_client),
    settings: MpesaSettings = Depends(get_settings),
) -> PaymentService:
    return PaymentService(db, mpesa, settings)


def _view(payment: Payment, side: str):
    return payment


# ------------------------------------------------------------------ buyer side
@router.post(
    "/enquiries/{enquiry_id}/payments",
    status_code=status.HTTP_202_ACCEPTED,
)
def pay_enquiry(
    enquiry_id: UUID,
    body: dict,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    """Sends an M-Pesa STK Push prompt to the buyer's phone. Poll GET /payments/{id} for the result."""
    response.headers.update(NO_STORE)
    payment = svc.initiate_payment(user, enquiry_id, body.get("phone_number"))
    return _view(payment, "buyer")


@router.post(
    "/enquiries/{enquiry_id}/confirm-receipt",
)
def confirm_receipt(
    enquiry_id: UUID,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    """Buyer confirms the goods arrived: enquiry becomes COMPLETED and the seller is paid."""
    response.headers.update(NO_STORE)
    return _view(svc.confirm_receipt(user, enquiry_id), "buyer")


# --------------------------------------------------- seller: payout details
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
    body: dict,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)
    return svc.set_payout_details(
        user, body.get("payout_phone"), body.get("payout_network")
    )


# ------------------------------------------------------------- M-Pesa callback
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
    """The body is ignored. We verify the signed URL, then ask Safaricom for the real status."""
    svc.handle_callback(kind, reference_id, token)
    return Response(status_code=status.HTTP_200_OK)


# ------------------------------------------------------------------- admin
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
        user, payment_status, payout_status, needs_review, limit, offset
    )
    return [_view(p, "admin") for p in rows]


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
    return _view(svc.admin_reconcile(user, payment_id), "admin")


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
    body: dict,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    """Return the buyer's money (only before the seller payout is sent)."""
    return _view(
        svc.refund_payment(user, payment_id, body.get("failure_reason")), "admin"
    )


@router.post("/admin/payments/{payment_id}/payout")
def admin_payout(
    payment_id: UUID,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    return _view(svc.initiate_payout(user, payment_id), "admin")


# ------------------------------------------------- shared reads (all parties)
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
    rows = svc.my_payments(user, side, payment_status, limit, offset)
    return [_view(p, side) for p in rows]


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
