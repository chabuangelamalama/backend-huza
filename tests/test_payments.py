"""Payment service tests against the Postgres test DB (skipped if it is not running).
MTN is replaced by FakeMomo, so nothing touches the network."""

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from core.payment_config import MomoSettings
from models import PaymentEvent
from models.business import ApprovalStatus, BusinessRole, PayoutNetwork
from models.enquiry import EnquiryStatus, FailureReason
from models.payment import PaymentStatus, PayoutStatus, RefundStatus
from models.user import UserRole
from schemas.payment import seller_view
from services.momo import MomoRejected, MomoResult, MomoTransient, callback_token
from services.payment_service import PaymentService, _now
from tests.test_models import (
    make_business,
    make_enquiry,
    make_listing,
    make_location,
    make_user,
)

PAYER = "250788123456"
SECRET = "s" * 40


class FakeMomo:
    def __init__(self):
        self.collections: dict[str, dict] = {}
        self.transfers: dict[str, dict] = {}
        self.reject_reason: str | None = None
        self.transfer_reject: str | None = None
        self.transient = False
        self.transfer_status = "SUCCESSFUL"

    def request_to_pay(self, **kw):
        if self.reject_reason:
            raise MomoRejected(self.reject_reason)
        if self.transient:
            raise MomoTransient("down")
        self.collections[kw["reference_id"]] = {
            **kw,
            "status": "PENDING",
            "reason": None,
        }

    def get_request_to_pay(self, ref):
        r = self.collections.get(ref)
        if r is None:
            return None
        return MomoResult(
            r["status"],
            r.get("report_amount", r["amount"]),
            "RWF",
            r["external_id"],
            "tx-1",
            r["reason"],
        )

    def transfer(self, **kw):
        if self.transfer_reject:
            raise MomoRejected(self.transfer_reject)
        self.transfers[kw["reference_id"]] = {
            **kw,
            "status": self.transfer_status,
            "reason": None,
        }

    def get_transfer(self, ref):
        r = self.transfers.get(ref)
        if r is None:
            return None
        return MomoResult(
            r["status"], r["amount"], "RWF", r["external_id"], "tx-2", r["reason"]
        )

    def is_account_active(self, msisdn):
        return msisdn.startswith("250788")

    def settle(self, status, reason=None, report_amount=None):
        for r in self.collections.values():
            r["status"], r["reason"] = status, reason
            if report_amount is not None:
                r["report_amount"] = report_amount

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
def momo():
    return FakeMomo()


def make_settings(**kw) -> MomoSettings:
    base = dict(
        currency="RWF",
        callback_secret=SECRET,
        attempt_cooldown_seconds=0,
        status_poll_min_interval_seconds=0,
        payout_change_hold_hours=24,
    )
    base.update(kw)
    return MomoSettings(**base)


@pytest.fixture
def svc(session, momo):
    return PaymentService(session, momo, make_settings())


@pytest.fixture
def world(session):
    loc = make_location(session)
    seller_b = make_business(
        session,
        loc,
        approval_status=ApprovalStatus.APPROVED,
        payout_phone="250788000111",
        payout_network=PayoutNetwork.MTN_MOMO,
    )
    buyer_b = make_business(
        session,
        loc,
        role=BusinessRole.BUYER,
        approval_status=ApprovalStatus.APPROVED,
        contact_email="b@example.rw",
    )
    other_b = make_business(
        session,
        loc,
        role=BusinessRole.BUYER,
        approval_status=ApprovalStatus.APPROVED,
        contact_email="o@example.rw",
    )
    listing = make_listing(session, seller_b, loc)
    enquiry = make_enquiry(session, listing, buyer_b, status=EnquiryStatus.AGREED)
    w = dict(
        seller=make_user(session, seller_b),
        buyer=make_user(session, buyer_b, phone=PAYER),
        other=make_user(session, other_b, phone="250788777777"),
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


def paid(svc, world, momo):
    """Buyer pays and MTN confirms. Returns the SUCCESSFUL payment."""
    p = pay(svc, world)
    momo.settle("SUCCESSFUL")
    return svc.reconcile_payment(p.payment_id)


def event_types(session, payment_id):
    rows = session.execute(
        select(PaymentEvent.event_type).where(PaymentEvent.payment_id == payment_id)
    ).scalars()
    return list(rows)


# ================================================================ initiate
def test_buyer_starts_payment_with_amount_from_enquiry(svc, world, momo):
    p = pay(svc, world)
    assert p.status == PaymentStatus.PENDING and p.amount == Decimal("5000")
    assert len(momo.collections) == 1


def test_non_party_and_seller_cannot_pay(svc, world):
    for who in ("other", "seller"):
        with pytest.raises(HTTPException) as e:
            svc.initiate_payment(world[who], world["enquiry"].enquiry_id, PAYER)
        assert e.value.status_code == 404  # not 403: ids must not be probeable


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
            world["buyer"], world["enquiry"].enquiry_id, "250788999999"
        )
    assert code(e) == "payer_phone_not_registered"


def test_registered_phone_rule_can_be_switched_off(session, momo, world):
    svc = PaymentService(
        session, momo, make_settings(require_registered_payer_phone=False)
    )
    p = svc.initiate_payment(
        world["buyer"], world["enquiry"].enquiry_id, "250788999999"
    )
    assert p.status == PaymentStatus.PENDING


def test_second_attempt_while_pending_is_blocked(svc, world):
    pay(svc, world)
    with pytest.raises(HTTPException) as e:
        pay(svc, world)
    assert code(e) == "payment_in_progress"


def test_mtn_rejection_marks_failed_and_buyer_can_retry(svc, world, momo):
    momo.reject_reason = "PAYER_NOT_FOUND"
    p = pay(svc, world)
    assert p.status == PaymentStatus.FAILED and p.failure_reason == "PAYER_NOT_FOUND"
    momo.reject_reason = None
    assert pay(svc, world).status == PaymentStatus.PENDING


def test_timeout_keeps_payment_pending_for_later_settlement(svc, world, momo):
    momo.transient = True
    assert pay(svc, world).status == PaymentStatus.PENDING


def test_attempt_cap_per_enquiry(svc, world, momo):
    momo.reject_reason = "EXPIRED"
    for _ in range(svc.s.max_attempts_per_enquiry):
        pay(svc, world)
    with pytest.raises(HTTPException) as e:
        pay(svc, world)
    assert e.value.status_code == 429


# ============================================================== settlement
def test_success_pays_enquiry_and_takes_stock_but_holds_the_payout(
    svc, world, momo, session
):
    p = paid(svc, world, momo)
    session.refresh(world["enquiry"])
    session.refresh(world["listing"])
    assert p.status == PaymentStatus.SUCCESSFUL and p.momo_transaction_id == "tx-1"
    assert world["enquiry"].status == EnquiryStatus.PAID
    assert world["listing"].quantity == Decimal("900")
    assert p.stock_deducted and p.payout_status == PayoutStatus.NOT_DUE
    assert momo.payouts() == []  # seller is NOT paid yet
    assert {"PAYMENT_CREATED", "PAYMENT_SUCCEEDED"} <= set(
        event_types(session, p.payment_id)
    )


def test_reconcile_twice_does_not_double_decrement(svc, world, momo, session):
    p = paid(svc, world, momo)
    svc.reconcile_payment(p.payment_id)
    session.refresh(world["listing"])
    assert world["listing"].quantity == Decimal("900")


def test_amount_mismatch_from_mtn_is_not_trusted(svc, world, momo):
    p = pay(svc, world)
    momo.settle("SUCCESSFUL", report_amount=Decimal("1"))
    p = svc.reconcile_payment(p.payment_id)
    assert p.status == PaymentStatus.PENDING and p.needs_review


def test_failed_payment_leaves_enquiry_agreed(svc, world, momo, session):
    p = pay(svc, world)
    momo.settle("FAILED", "NOT_ENOUGH_FUNDS")
    p = svc.reconcile_payment(p.payment_id)
    session.refresh(world["enquiry"])
    assert p.status == PaymentStatus.FAILED and p.failure_reason == "NOT_ENOUGH_FUNDS"
    assert world["enquiry"].status == EnquiryStatus.AGREED


# ============================================== receipt -> payout (+ fee)
def test_buyer_confirms_receipt_and_seller_is_paid_minus_fee(session, momo, world):
    svc = PaymentService(session, momo, make_settings(huza_fee_percent=Decimal("5")))
    paid(svc, world, momo)
    p = svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    session.refresh(world["enquiry"])
    assert (
        world["enquiry"].status == EnquiryStatus.COMPLETED
        and world["enquiry"].closed_at
    )
    assert p.fee_amount == Decimal("250") and p.payout_amount == Decimal("4750")
    [transfer] = momo.payouts()
    assert (
        transfer["amount"] == Decimal("4750")
        and transfer["payee_msisdn"] == "250788000111"
    )
    p = svc.reconcile_payout(p.payment_id)
    assert p.payout_status == PayoutStatus.PAID and p.paid_out_at
    assert "PAYOUT_PAID" in event_types(session, p.payment_id)


def test_only_the_buyer_can_confirm_and_only_when_paid(svc, world, momo):
    for who in ("seller", "other"):
        with pytest.raises(HTTPException) as e:
            svc.confirm_receipt(world[who], world["enquiry"].enquiry_id)
        assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:  # still AGREED, nothing paid
        svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    assert code(e) == "not_completable"


def test_confirming_twice_does_not_pay_twice(svc, world, momo):
    paid(svc, world, momo)
    svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    with pytest.raises(HTTPException):
        svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    assert len(momo.payouts()) == 1


def test_on_paid_trigger_pays_the_seller_immediately(session, momo, world):
    svc = PaymentService(session, momo, make_settings(payout_trigger="ON_PAID"))
    p = paid(svc, world, momo)
    assert p.payout_status == PayoutStatus.PENDING and p.payout_reference
    assert len(momo.payouts()) == 1


def test_enquiry_module_hook_release_payout(svc, world, momo, session):
    p = paid(svc, world, momo)
    world["enquiry"].status = EnquiryStatus.COMPLETED  # set by another module
    session.commit()
    svc.release_payout(world["enquiry"].enquiry_id)
    svc.release_payout(world["enquiry"].enquiry_id)  # safe twice
    assert len(momo.payouts()) == 1
    assert svc.reconcile_payout(p.payment_id).payout_status == PayoutStatus.PAID


def test_failed_payout_stores_reason_and_admin_retry_uses_new_reference(
    svc, world, momo, session
):
    momo.transfer_status = "FAILED"
    paid(svc, world, momo)
    p = svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    first_ref = p.payout_reference
    p = svc.reconcile_payout(p.payment_id)
    assert (
        p.payout_status == PayoutStatus.FAILED and p.payout_failure_reason == "UNKNOWN"
    )
    assert p.needs_review
    momo.transfer_status = "SUCCESSFUL"
    p = svc.initiate_payout(world["admin"], p.payment_id)
    assert p.payout_reference != first_ref
    assert svc.reconcile_payout(p.payment_id).payout_status == PayoutStatus.PAID
    assert "PAYOUT_FAILED" in event_types(session, p.payment_id)


def test_mtn_rejecting_the_payout_marks_it_failed(svc, world, momo):
    paid(svc, world, momo)
    momo.transfer_reject = "PAYEE_NOT_FOUND"
    p = svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    assert (
        p.payout_status == PayoutStatus.FAILED
        and p.payout_failure_reason == "PAYEE_NOT_FOUND"
    )


# ================================================ payout-number change hold
def test_replacing_the_payout_number_holds_payouts(svc, world, momo, session):
    svc.set_payout_details(world["seller"], "250788999000", PayoutNetwork.MTN_MOMO)
    paid(svc, world, momo)
    p = svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    assert p.payout_status == PayoutStatus.PENDING and p.payout_reference is None
    assert momo.payouts() == []
    with pytest.raises(HTTPException) as e:
        svc.initiate_payout(world["admin"], p.payment_id)
    assert code(e) == "payout_on_hold"
    svc.s.payout_change_hold_hours = 0  # hold over
    result = svc.sweep(None)
    assert result["payouts_started"] == 1 and len(momo.payouts()) == 1


def test_first_time_payout_number_has_no_hold(svc, world, session):
    world["seller_b"].payout_phone = None
    world["seller_b"].payout_network = None
    session.commit()
    svc.set_payout_details(world["seller"], "250788999000", PayoutNetwork.MTN_MOMO)
    types = session.execute(select(PaymentEvent.event_type)).scalars().all()
    assert "PAYOUT_DETAILS_SET" in types and "PAYOUT_DETAILS_REPLACED" not in types


def test_set_payout_details_checks_account_and_role(svc, world):
    with pytest.raises(HTTPException) as e:
        svc.set_payout_details(world["seller"], "250791234567", PayoutNetwork.MTN_MOMO)
    assert code(e) == "payout_number_invalid"
    with pytest.raises(HTTPException) as e:
        svc.set_payout_details(world["buyer"], "250788999000", PayoutNetwork.MTN_MOMO)
    assert e.value.status_code == 403


# ================================================================= refunds
def test_oversold_payment_is_refunded_automatically(svc, world, momo, session):
    p = pay(svc, world)
    world["listing"].quantity = Decimal("50")  # someone else took the stock
    session.commit()
    momo.settle("SUCCESSFUL")
    p = svc.reconcile_payment(p.payment_id)
    session.refresh(world["enquiry"])
    session.refresh(world["listing"])
    assert p.needs_review and not p.stock_deducted
    assert world["enquiry"].status == EnquiryStatus.AGREED
    assert world["listing"].quantity == Decimal("50")
    [refund] = momo.refunds()
    assert refund["payee_msisdn"] == PAYER and refund["amount"] == Decimal("5000")
    p = svc.reconcile_refund(p.payment_id)
    assert p.refund_status == RefundStatus.REFUNDED and p.refunded_at
    assert momo.payouts() == []


def test_conflict_stays_for_review_when_auto_refund_is_off(session, momo, world):
    svc = PaymentService(session, momo, make_settings(auto_refund_on_conflict=False))
    p = pay(svc, world)
    world["enquiry"].status = EnquiryStatus.CANCELLED
    world["enquiry"].failure_reason = FailureReason.OTHER
    session.commit()
    momo.settle("SUCCESSFUL")
    p = svc.reconcile_payment(p.payment_id)
    assert (
        p.needs_review and p.refund_status == RefundStatus.NONE and momo.refunds() == []
    )


def test_admin_refund_cancels_the_deal_and_restores_stock(svc, world, momo, session):
    p = paid(svc, world, momo)
    p = svc.refund_payment(world["admin"], p.payment_id, FailureReason.QUALITY)
    session.refresh(world["enquiry"])
    session.refresh(world["listing"])
    assert world["enquiry"].status == EnquiryStatus.CANCELLED
    assert world["enquiry"].failure_reason == FailureReason.QUALITY
    assert world["listing"].quantity == Decimal("1000")
    assert p.refund_status == RefundStatus.PENDING and not p.stock_deducted
    assert svc.reconcile_refund(p.payment_id).refund_status == RefundStatus.REFUNDED
    assert momo.payouts() == []


def test_refund_is_blocked_after_the_seller_was_paid_and_for_non_admins(
    svc, world, momo
):
    p = paid(svc, world, momo)
    with pytest.raises(HTTPException) as e:
        svc.refund_payment(world["buyer"], p.payment_id)
    assert e.value.status_code == 403
    svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    svc.reconcile_payout(p.payment_id)
    with pytest.raises(HTTPException) as e:
        svc.refund_payment(world["admin"], p.payment_id)
    assert code(e) == "refund_not_allowed"


def test_failed_refund_is_flagged_and_can_be_retried(svc, world, momo):
    p = paid(svc, world, momo)
    momo.transfer_reject = "PAYEE_NOT_FOUND"
    p = svc.refund_payment(world["admin"], p.payment_id)
    assert p.refund_status == RefundStatus.FAILED and p.needs_review
    momo.transfer_reject = None
    p = svc.refund_payment(world["admin"], p.payment_id)
    assert svc.reconcile_refund(p.payment_id).refund_status == RefundStatus.REFUNDED


# ============================================================ sweep / admin
def test_unconfirmed_deals_are_completed_and_paid_after_the_window(
    svc, world, momo, session
):
    p = paid(svc, world, momo)
    p.paid_at = _now() - timedelta(days=svc.s.auto_release_days + 1)
    session.commit()
    result = svc.sweep(None)
    session.refresh(world["enquiry"])
    assert result["auto_completed"] == 1
    assert world["enquiry"].status == EnquiryStatus.COMPLETED
    assert len(momo.payouts()) == 1


def test_recent_deals_are_left_alone_by_the_sweep(svc, world, momo):
    paid(svc, world, momo)
    assert svc.sweep(None)["auto_completed"] == 0


def test_sweep_settles_pending_payments_and_flags_stale_ones(svc, world, momo, session):
    p = pay(svc, world)
    p.created_at = _now() - timedelta(hours=svc.s.stale_pending_review_hours + 1)
    p.updated_at = _now() - timedelta(minutes=5)
    session.commit()
    result = svc.sweep(None)
    session.refresh(p)
    assert (
        result["flagged"] == 1
        and p.needs_review
        and p.review_reason == "PENDING_TOO_LONG"
    )
    momo.settle("SUCCESSFUL")
    p.updated_at = _now() - timedelta(minutes=5)
    session.commit()
    svc.sweep(None)
    session.refresh(p)
    assert p.status == PaymentStatus.SUCCESSFUL


def test_admin_only_actions(svc, world, momo):
    p = pay(svc, world)
    for fn in (
        svc.admin_reconcile,
        svc.initiate_payout,
        svc.refund_payment,
        svc.admin_events,
    ):
        with pytest.raises(HTTPException) as e:
            fn(world["buyer"], p.payment_id)
        assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        svc.sweep(world["seller"])
    assert e.value.status_code == 403


def test_admin_can_list_events_and_filter_review(svc, world, momo):
    p = paid(svc, world, momo)
    events = svc.admin_events(world["admin"], p.payment_id)
    assert [e.event_type for e in events][:1] == ["PAYMENT_CREATED"]
    assert all("phone" not in str(e.detail).lower() for e in events)
    assert svc.admin_list(world["admin"], None, None, True, 10, 0) == []
    assert len(svc.admin_list(world["admin"], None, None, None, 10, 0)) == 1


# ============================================================ reads / callback
def test_reads_are_limited_to_parties(svc, world):
    p = pay(svc, world)
    assert svc.get_payment_for_actor(world["buyer"], p.payment_id)[1] == "buyer"
    assert svc.get_payment_for_actor(world["seller"], p.payment_id)[1] == "seller"
    assert svc.get_payment_for_actor(world["admin"], p.payment_id)[1] == "admin"
    with pytest.raises(HTTPException) as e:
        svc.get_payment_for_actor(world["other"], p.payment_id)
    assert e.value.status_code == 404


def test_seller_view_hides_buyer_phone_but_shows_fee_and_payout(svc, world):
    data = seller_view(pay(svc, world)).model_dump()
    assert "payer_phone" not in data
    assert {"fee_amount", "payout_amount", "payout_status"} <= set(data)


def test_callback_needs_valid_signature_and_only_triggers_a_recheck(svc, world, momo):
    p = pay(svc, world)
    with pytest.raises(HTTPException) as e:
        svc.handle_callback("collection", p.reference_id, "bad-token")
    assert e.value.status_code == 404
    good = callback_token(SECRET, "collection", p.reference_id)
    svc.handle_callback("collection", p.reference_id, good)  # MTN still says PENDING
    assert (
        svc.get_payment_for_actor(world["buyer"], p.payment_id)[0].status
        == PaymentStatus.PENDING
    )
    momo.settle("SUCCESSFUL")
    svc.handle_callback("collection", p.reference_id, good)
    assert (
        svc.get_payment_for_actor(world["buyer"], p.payment_id)[0].status
        == PaymentStatus.SUCCESSFUL
    )
