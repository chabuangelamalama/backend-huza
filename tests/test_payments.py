"""Payment service tests against the Postgres test DB (skipped if it is not running)."""

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from core.payment_config import MpesaSettings
from models import PaymentEvent
from models.business import ApprovalStatus, BusinessRole, PayoutNetwork
from models.enquiry import EnquiryStatus
from models.payment import PaymentStatus
from models.user import UserRole
from services.mpesa import MpesaRejected, MpesaResult, MpesaTransient
from services.payment_service import PaymentService
from tests.test_models import (
    make_business,
    make_enquiry,
    make_listing,
    make_location,
    make_user,
)

PAYER = "254712345678"
PHONE_NUMBER = "254712345678"
SECRET = "s" * 40
CHECKOUT_ID = "ws_CO_28102026165942123"


class FakeMpesa:
    def __init__(self):
        self.collections: dict[str, dict] = {}
        self.transfers: dict[str, dict] = {}
        self.reject_reason: str | None = None
        self.transfer_reject: str | None = None
        self.transient = False
        self.transfer_status = "SUCCESSFUL"
        self.last_reference_id: str | None = None

    def request_to_pay(self, **kw) -> str:
        if self.reject_reason:
            raise MpesaRejected(self.reject_reason)
        if self.transient:
            raise MpesaTransient("down")
        self.last_reference_id = kw["reference_id"]
        self.collections[CHECKOUT_ID] = {
            **kw,
            "status": "PENDING",
            "reason": None,
        }
        return CHECKOUT_ID

    def get_request_to_pay(self, checkout_request_id: str):
        r = self.collections.get(checkout_request_id)
        if r is None:
            return None
        return MpesaResult(
            r["status"],
            r["amount"],
            "KES",
            checkout_request_id,
            "tx-1",
            r["reason"],
        )

    def transfer(self, **kw):
        if self.transfer_reject:
            raise MpesaRejected(self.transfer_reject)
        self.transfers[kw["reference_id"]] = {
            **kw,
            "status": self.transfer_status,
            "reason": None,
        }

    def get_transfer(self, ref):
        r = self.transfers.get(ref)
        if r is None:
            return None
        return MpesaResult(
            r["status"], r["amount"], "KES", r["external_id"], "tx-2", r["reason"]
        )

    def settle(self, status, reason=None):
        for r in self.collections.values():
            r["status"], r["reason"] = status, reason

    def payouts(self):
        return [
            t
            for t in self.transfers.values()
            if not t["external_id"].startswith("refund-")
        ]

    def refunds(self):
        return [
            t for t in self.transfers.values() if t["external_id"].startswith("refund-")
        ]


@pytest.fixture
def mpesa():
    return FakeMpesa()


def make_settings(**kw) -> MpesaSettings:
    base = dict(
        currency="KES",
        callback_secret=SECRET,
        attempt_cooldown_seconds=0,
        status_poll_min_interval_seconds=0,
        payout_change_hold_hours=24,
    )
    base.update(kw)
    return MpesaSettings(**base)


@pytest.fixture
def svc(session, mpesa):
    return PaymentService(session, mpesa, make_settings())


@pytest.fixture
def world(session):
    loc = make_location(session)
    seller_b = make_business(
        session,
        loc,
        approval_status=ApprovalStatus.APPROVED,
        payout_phone="254712000111",
        payout_network=PayoutNetwork.MPESA,
    )
    buyer_b = make_business(
        session,
        loc,
        role=BusinessRole.BUYER,
        approval_status=ApprovalStatus.APPROVED,
        contact_email="b@example.ke",
    )
    other_b = make_business(
        session,
        loc,
        role=BusinessRole.BUYER,
        approval_status=ApprovalStatus.APPROVED,
        contact_email="o@example.ke",
    )
    listing = make_listing(session, seller_b, loc)
    enquiry = make_enquiry(session, listing, buyer_b, status=EnquiryStatus.AGREED)
    w = dict(
        seller=make_user(session, seller_b),
        buyer=make_user(session, buyer_b, phone=PAYER),
        other=make_user(session, other_b, phone="254712777777"),
        admin=make_user(session, role=UserRole.ADMIN),
        seller_b=seller_b,
        buyer_b=buyer_b,
        listing=listing,
        enquiry=enquiry,
    )
    session.commit()
    return w


def code(exc) -> str:
    return exc.value.detail["code"]


def pay(svc, world):
    return svc.initiate_payment(world["buyer"], world["enquiry"].enquiry_id, PAYER)


def paid(svc, world, mpesa):
    """Buyer pays and M-Pesa confirms. Returns the SUCCESSFUL payment."""
    p = pay(svc, world)
    mpesa.settle("SUCCESSFUL")
    return svc.reconcile_payment(p.payment_id)


def event_types(session, payment_id):
    rows = session.execute(
        select(PaymentEvent.event_type).where(PaymentEvent.payment_id == payment_id)
    ).scalars()
    return list(rows)


# ================================================================ initiate
def test_buyer_starts_payment_with_amount_from_enquiry(svc, world, mpesa):
    p = pay(svc, world)
    assert p.status == PaymentStatus.PENDING and p.amount == Decimal("5000")
    assert len(mpesa.collections) == 1


def test_non_party_and_seller_cannot_pay(svc, world):
    for who in ("other", "seller"):
        with pytest.raises(HTTPException) as e:
            svc.initiate_payment(world[who], world["enquiry"].enquiry_id, PAYER)
        assert e.value.status_code == 404


def test_enquiry_must_be_agreed(svc, world, session):
    world["enquiry"].status = EnquiryStatus.ENQUIRY
    session.commit()
    with pytest.raises(HTTPException) as e:
        pay(svc, world)
    assert code(e) == "enquiry_not_payable"


def test_seller_needs_payout_details(svc, world, session):
    world["seller_b"].payout_phone = None
    world["seller_b"].payout_network = None
    session.commit()
    with pytest.raises(HTTPException) as e:
        pay(svc, world)
    assert code(e) == "seller_payout_not_configured"


def test_payer_must_use_a_number_from_their_profile(svc, world):
    with pytest.raises(HTTPException) as e:
        svc.initiate_payment(
            world["buyer"], world["enquiry"].enquiry_id, "254712999999"
        )
    assert code(e) == "payer_phone_not_registered"


def test_registered_phone_rule_can_be_switched_off(session, mpesa, world):
    svc = PaymentService(
        session, mpesa, make_settings(require_registered_payer_phone=False)
    )
    p = svc.initiate_payment(
        world["buyer"], world["enquiry"].enquiry_id, "254712999999"
    )
    assert p.status == PaymentStatus.PENDING


def test_second_attempt_while_pending_is_blocked(svc, world):
    pay(svc, world)
    with pytest.raises(HTTPException) as e:
        pay(svc, world)
    assert code(e) == "payment_in_progress"


def test_mpesa_rejection_marks_failed_and_buyer_can_retry(svc, world, mpesa):
    mpesa.reject_reason = "PAYER_NOT_FOUND"
    p = pay(svc, world)
    assert p.status == PaymentStatus.FAILED and p.failure_reason == "PAYER_NOT_FOUND"
    mpesa.reject_reason = None
    assert pay(svc, world).status == PaymentStatus.PENDING


def test_timeout_keeps_payment_pending_for_later_settlement(svc, world, mpesa):
    mpesa.transient = True
    assert pay(svc, world).status == PaymentStatus.PENDING


def test_attempt_cap_per_enquiry(svc, world, mpesa):
    mpesa.reject_reason = "EXPIRED"
    for _ in range(svc.s.max_attempts_per_enquiry):
        pay(svc, world)
    with pytest.raises(HTTPException) as e:
        pay(svc, world)
    assert e.value.status_code == 429


# ============================================================== settlement
def test_success_pays_enquiry_and_takes_stock_but_holds_the_payout(
    svc, world, mpesa, session
):
    p = paid(svc, world, mpesa)
    session.refresh(world["enquiry"])
    session.refresh(world["listing"])
    assert p.status == PaymentStatus.SUCCESSFUL
