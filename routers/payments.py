"""Payment endpoints (buyer, seller, M-Pesa callback, admin)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from core.payment_config import MpesaSettings
from core.payment_deps import (
    get_current_user,
    get_db,
    get_mpesa_client,
    get_settings,
)
from models.user import User
from schemas.payment import (
    AdminPaymentsFilter,
    InitiatePaymentRequest,
    MyPaymentsFilter,
    PaymentEventOut,
    PayoutDetailsRequest,
    RefundRequest,
    payment_view,
)
from services.mpesa import MpesaGateway
from services.payment_service import PaymentService

router = APIRouter(tags=["payments"])

NO_STORE = {"Cache-Control": "no-store"}


def get_service(
    db: Session = Depends(get_db),
    mpesa: MpesaGateway = Depends(get_mpesa_client),
    settings: MpesaSettings = Depends(get_settings),
) -> PaymentService:
    return PaymentService(db, mpesa, settings)


@router.post(
    "/enquiries/{enquiry_id}/payments",
    status_code=status.HTTP_202_ACCEPTED,
)
def pay_enquiry(
    enquiry_id: UUID,
    body: InitiatePaymentRequest,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    """Initiate an M-Pesa STK Push for an enquiry."""
    response.headers.update(NO_STORE)
    payment = svc.initiate_payment(user, enquiry_id, body.phone_number)
    return payment_view(payment, "buyer")


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
    return payment_view(payment, "buyer")


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
    return svc.set_payout_details(user, body.payout_phone, body.payout_network)


@router.api_route(
    "/payments/mpesa/callback/{kind}/{reference_id}/{token}",
    methods=["POST", "PUT"],
    include_in_schema=False,
)
async def mpesa_callback(
    kind: str,
    reference_id: str,
    token: str,
    request: Request,
    svc: PaymentService = Depends(get_service),
):
    """Receive a Daraja callback or a signed empty-body reachability ping."""
    svc.handle_raw_callback(kind, reference_id, token, await request.body())
    return Response(status_code=status.HTTP_200_OK)


@router.get("/admin/payments")
def admin_list_payments(
    filters: Annotated[AdminPaymentsFilter, Query()],
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    rows = svc.admin_list(
        user,
        filters.status,
        filters.payout_status,
        filters.needs_review,
        filters.limit,
        filters.offset,
    )
    return [payment_view(payment, "admin") for payment in rows]


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
    return payment_view(svc.admin_reconcile(user, payment_id), "admin")


@router.get("/admin/payments/{payment_id}/events")
def admin_events(
    payment_id: UUID,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    return [
        PaymentEventOut.model_validate(event)
        for event in svc.admin_events(user, payment_id)
    ]


@router.post("/admin/payments/{payment_id}/refund")
def admin_refund(
    payment_id: UUID,
    body: RefundRequest,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    payment = svc.refund_payment(user, payment_id, body.failure_reason)
    return payment_view(payment, "admin")


@router.post("/admin/payments/{payment_id}/payout")
def admin_payout(
    payment_id: UUID,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    return payment_view(svc.initiate_payout(user, payment_id), "admin")


@router.get("/payments")
def my_payments(
    filters: Annotated[MyPaymentsFilter, Query()],
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)
    rows, side = svc.list_my_payments(
        user, filters.side, filters.status, filters.limit, filters.offset
    )
    return [payment_view(payment, side) for payment in rows]


@router.get("/payments/{payment_id}")
def get_payment(
    payment_id: UUID,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)
    payment, side = svc.get_payment_for_actor(user, payment_id)
    return payment_view(payment, side)


@router.get("/enquiries/{enquiry_id}/payments")
def enquiry_payments(
    enquiry_id: UUID,
    response: Response,
    user: User = Depends(get_current_user),
    svc: PaymentService = Depends(get_service),
):
    response.headers.update(NO_STORE)
    payment, side = svc.get_payment_for_enquiry(user, enquiry_id)
    return payment_view(payment, side)
