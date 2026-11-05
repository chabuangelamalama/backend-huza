"""Payment service tests against the Postgres test DB (skipped if it is not running)."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from core.payment_config import MpesaSettings
from models import Payment, PaymentEvent
from models.business import ApprovalStatus, BusinessRole, PayoutNetwork
from models.enquiry import EnquiryStatus
from models.payment import PaymentStatus, PayoutStatus
from models.user import UserRole
from repositories import payment_repository as repo
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
            "external_id": kw["reference_id"],
            "status": self.transfer_status,
            "reason": None,
        }
        return f"conv-{kw['reference_id'][:8]}"

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
        status_poll_min_interval_seconds=1,
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


def test_success_pays_enquiry_and_takes_stock_but_holds_the_payout(
    svc, world, mpesa, session
):
    p = paid(svc, world, mpesa)
    session.refresh(world["enquiry"])
    session.refresh(world["listing"])
    assert p.status == PaymentStatus.SUCCESSFUL


def _payment_row(session, enquiry, status, minutes_ago):
    row = Payment(
        enquiry_id=enquiry.enquiry_id,
        amount=enquiry.total_amount,
        phone_number=PAYER,
        reference_id=str(uuid.uuid4()),
        status=status,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    session.add(row)
    session.flush()
    return row


def test_enquiry_lookup_prefers_the_successful_payment(session, world):
    enquiry = world["enquiry"]
    assert repo.get_payment_by_enquiry_id(session, enquiry.enquiry_id) is None

    failed = _payment_row(session, enquiry, PaymentStatus.FAILED, 30)
    assert repo.get_payment_by_enquiry_id(session, enquiry.enquiry_id) is failed

    successful = _payment_row(session, enquiry, PaymentStatus.SUCCESSFUL, 20)
    _payment_row(session, enquiry, PaymentStatus.FAILED, 10)
    assert repo.get_payment_by_enquiry_id(session, enquiry.enquiry_id) is successful


def test_enquiry_lookup_returns_the_latest_attempt_without_a_success(session, world):
    enquiry = world["enquiry"]
    _payment_row(session, enquiry, PaymentStatus.FAILED, 30)
    latest = _payment_row(session, enquiry, PaymentStatus.PENDING, 5)
    assert repo.get_payment_by_enquiry_id(session, enquiry.enquiry_id) is latest


def test_attempts_are_counted_per_payer_phone(session, world):
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    _payment_row(session, world["enquiry"], PaymentStatus.FAILED, 10)
    _payment_row(session, world["enquiry"], PaymentStatus.FAILED, 120)
    assert repo.count_attempts_by_phone_since(session, PAYER, since) == 1
    assert repo.count_attempts_by_phone_since(session, "254799999999", since) == 0


def test_parties_read_the_payment_of_an_enquiry(svc, world):
    p = pay(svc, world)
    enquiry_id = world["enquiry"].enquiry_id
    for who, side in (("buyer", "buyer"), ("seller", "seller"), ("admin", "admin")):
        found, seen_as = svc.get_payment_for_enquiry(world[who], enquiry_id)
        assert found.payment_id == p.payment_id and seen_as == side
    with pytest.raises(HTTPException) as e:
        svc.get_payment_for_enquiry(world["other"], enquiry_id)
    assert e.value.status_code == 404


def test_reading_an_enquiry_without_payments_is_not_found(svc, world):
    with pytest.raises(HTTPException) as e:
        svc.get_payment_for_enquiry(world["buyer"], world["enquiry"].enquiry_id)
    assert code(e) == "not_found"


def test_buyer_confirms_receipt_after_a_successful_payment(svc, world, mpesa):
    p = paid(svc, world, mpesa)
    assert p.status == PaymentStatus.SUCCESSFUL
    confirmed = svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    assert confirmed.payment_id == p.payment_id
    assert confirmed.payout_status == PayoutStatus.PENDING


def test_receipt_cannot_be_confirmed_before_payment_succeeds(svc, world):
    enquiry_id = world["enquiry"].enquiry_id
    with pytest.raises(HTTPException) as e:
        svc.confirm_receipt(world["buyer"], enquiry_id)
    assert e.value.status_code == 404
    pay(svc, world)
    with pytest.raises(HTTPException) as e:
        svc.confirm_receipt(world["buyer"], enquiry_id)
    assert code(e) == "payment_not_successful"


def test_only_the_buyer_confirms_receipt(svc, world, mpesa):
    paid(svc, world, mpesa)
    for who in ("seller", "other"):
        with pytest.raises(HTTPException) as e:
            svc.confirm_receipt(world[who], world["enquiry"].enquiry_id)
        assert e.value.status_code == 404


def test_successful_payment_marks_the_enquiry_paid(svc, world, mpesa, session):
    paid(svc, world, mpesa)
    session.refresh(world["enquiry"])
    assert world["enquiry"].status == EnquiryStatus.PAID


def test_reading_a_pending_payment_asks_mpesa_for_the_result(svc, world, mpesa):
    p = pay(svc, world)
    mpesa.settle("SUCCESSFUL")  # Safaricom has the result but no callback came

    found, _ = svc.get_payment_for_enquiry(world["buyer"], world["enquiry"].enquiry_id)

    assert found.payment_id == p.payment_id
    assert found.status == PaymentStatus.SUCCESSFUL


def test_status_refresh_survives_mpesa_being_down(svc, world, mpesa):
    pay(svc, world)

    def down(_checkout_id):
        raise MpesaTransient("down")

    mpesa.get_request_to_pay = down
    found, _ = svc.get_payment_for_enquiry(world["buyer"], world["enquiry"].enquiry_id)
    assert found.status == PaymentStatus.PENDING


def test_confirm_receipt_completes_enquiry_and_pays_the_seller(
    svc, world, mpesa, session
):
    p = paid(svc, world, mpesa)

    confirmed = svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)

    session.refresh(world["enquiry"])
    assert world["enquiry"].status == EnquiryStatus.COMPLETED
    assert world["enquiry"].closed_at is not None
    assert confirmed.payout_status == PayoutStatus.PENDING
    assert confirmed.payout_reference is not None
    transfer = mpesa.transfers[str(p.payment_id)]
    assert transfer["phone_number"] == world["seller_b"].payout_phone
    assert transfer["amount"] == p.amount
    assert "RECEIPT_CONFIRMED" in event_types(session, p.payment_id)
    assert "PAYOUT_REQUESTED" in event_types(session, p.payment_id)


def test_receipt_can_only_be_confirmed_once(svc, world, mpesa):
    paid(svc, world, mpesa)
    svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    with pytest.raises(HTTPException) as e:
        svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    assert code(e) == "receipt_already_confirmed"
    assert len(mpesa.transfers) == 1


def test_rejected_payout_keeps_the_confirmation_and_admin_can_retry(
    svc, world, mpesa, session
):
    p = paid(svc, world, mpesa)
    mpesa.transfer_reject = "B2C payouts are not configured"

    confirmed = svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)

    session.refresh(world["enquiry"])
    assert world["enquiry"].status == EnquiryStatus.COMPLETED
    assert confirmed.payout_status == PayoutStatus.FAILED
    assert "not configured" in confirmed.payout_failure_reason

    mpesa.transfer_reject = None
    retried = svc.initiate_payout(world["admin"], p.payment_id)
    assert retried.payout_status == PayoutStatus.PENDING
    assert str(p.payment_id) in mpesa.transfers


def test_admin_cannot_send_a_second_payout_while_one_is_in_flight(svc, world, mpesa):
    p = paid(svc, world, mpesa)
    svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    with pytest.raises(HTTPException) as e:
        svc.initiate_payout(world["admin"], p.payment_id)
    assert code(e) == "payout_in_progress"


def test_no_automatic_payout_when_auto_payout_is_off(session, world, mpesa):
    svc = PaymentService(session, mpesa, make_settings(auto_payout=False))
    paid(svc, world, mpesa)
    confirmed = svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)
    assert confirmed.payout_status == PayoutStatus.PENDING
    assert mpesa.transfers == {}


def stk_success(payment, receipt="UK5IR0ZYZO"):
    return {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "m-1",
                "CheckoutRequestID": payment.mpesa_checkout_request_id,
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": float(payment.amount)},
                        {"Name": "MpesaReceiptNumber", "Value": receipt},
                        {"Name": "PhoneNumber", "Value": int(payment.phone_number)},
                    ]
                },
            }
        }
    }


def send_callback(svc, payment, body):
    from services.mpesa import callback_token

    token = callback_token(SECRET, "collection", payment.reference_id)
    svc.handle_callback("collection", payment.reference_id, token, body)


def test_callback_landing_during_a_status_check_settles_only_once(
    svc, world, mpesa, session
):
    from sqlalchemy import text

    p = pay(svc, world)
    stock_before = world["listing"].quantity
    real_query = mpesa.get_request_to_pay

    def query_while_callback_lands(checkout_id):
        # The callback commits in another request while we wait on Safaricom;
        # this session still holds the old PENDING copy of the payment.
        session.execute(
            text(
                "UPDATE payment SET status = 'SUCCESSFUL', stock_deducted = true, "
                "mpesa_transaction_id = 'UK5IR0ZYZO' WHERE payment_id = :pid"
            ),
            {"pid": p.payment_id.hex},
        )
        session.execute(
            text("UPDATE listing SET quantity = quantity - :q WHERE listing_id = :lid"),
            {"q": world["enquiry"].quantity, "lid": world["listing"].listing_id.hex},
        )
        mpesa.settle("SUCCESSFUL")
        return real_query(checkout_id)

    mpesa.get_request_to_pay = query_while_callback_lands
    svc.reconcile_payment(p.payment_id)

    session.expire_all()
    listing = session.get(type(world["listing"]), world["listing"].listing_id)
    assert listing.quantity == stock_before - world["enquiry"].quantity
    assert event_types(session, p.payment_id).count("PAYMENT_SETTLED") == 0
    assert session.get(Payment, p.payment_id).mpesa_receipt_number == "UK5IR0ZYZO"


def test_late_callback_replaces_the_checkout_id_with_the_real_receipt(
    svc, world, mpesa, session
):
    p = paid(svc, world, mpesa)  # settled by a status check: no receipt yet
    assert p.mpesa_receipt_number == p.mpesa_checkout_request_id

    send_callback(svc, p, stk_success(p))

    session.expire_all()
    settled = session.get(Payment, p.payment_id)
    assert settled.mpesa_receipt_number == "UK5IR0ZYZO"
    assert event_types(session, p.payment_id).count("PAYMENT_SETTLED") == 1


def test_callback_settles_a_pending_payment(svc, world, mpesa, session):
    p = pay(svc, world)
    send_callback(svc, p, stk_success(p))
    session.expire_all()
    settled = session.get(Payment, p.payment_id)
    assert settled.status == PaymentStatus.SUCCESSFUL
    assert settled.mpesa_receipt_number == "UK5IR0ZYZO"
    assert session.get(type(world["enquiry"]), world["enquiry"].enquiry_id).status == (
        EnquiryStatus.PAID
    )


def b2c_result(code, desc="The service request is processed successfully."):
    return {
        "Result": {
            "ResultType": 0,
            "ResultCode": code,
            "ResultDesc": desc,
            "OriginatorConversationID": "oc-1",
            "ConversationID": "AG_20261105_0100105800tabkuiic98",
            "TransactionID": "UK5B2C0001",
        }
    }


def send_b2c(svc, payment, body):
    from services.mpesa import callback_token

    ref = str(payment.payment_id)
    svc.handle_callback(
        "disbursement", ref, callback_token(SECRET, "disbursement", ref), body
    )


def confirmed(svc, world, mpesa):
    paid(svc, world, mpesa)
    return svc.confirm_receipt(world["buyer"], world["enquiry"].enquiry_id)


def test_b2c_success_callback_marks_the_payout_paid(svc, world, mpesa, session):
    p = confirmed(svc, world, mpesa)
    send_b2c(svc, p, b2c_result(0))
    session.expire_all()
    p = session.get(Payment, p.payment_id)
    assert p.payout_status == PayoutStatus.PAID
    assert p.paid_out_at is not None
    assert "PAYOUT_PAID" in event_types(session, p.payment_id)


@pytest.mark.parametrize(
    "code, desc",
    [
        (2001, "The initiator information is invalid."),
        ("SFC_IC0003", "Operator does not exist."),
    ],
)
def test_b2c_failure_callback_marks_the_payout_failed_with_the_reason(
    svc, world, mpesa, session, code, desc
):
    p = confirmed(svc, world, mpesa)
    send_b2c(svc, p, b2c_result(code, desc))
    session.expire_all()
    p = session.get(Payment, p.payment_id)
    assert p.payout_status == PayoutStatus.FAILED
    assert p.payout_failure_reason == f"{code}: {desc}"
    assert not p.needs_review
    assert "PAYOUT_FAILED" in event_types(session, p.payment_id)


def test_failed_payout_can_be_retried_by_an_admin(svc, world, mpesa, session):
    p = confirmed(svc, world, mpesa)
    send_b2c(svc, p, b2c_result("SFC_IC0003", "Operator does not exist."))
    retried = svc.initiate_payout(world["admin"], p.payment_id)
    assert retried.payout_status == PayoutStatus.PENDING


def wrongly_failed(svc, world, mpesa):
    """What happened on Render: a status check marked a live payment FAILED."""
    p = pay(svc, world)
    mpesa.settle("FAILED", "The transaction is still under processing")
    svc.reconcile_payment(p.payment_id)
    assert p.status == PaymentStatus.FAILED
    return p


def test_success_callback_after_a_wrong_failure_records_the_payment(
    svc, world, mpesa, session
):
    p = wrongly_failed(svc, world, mpesa)
    stock_before = world["listing"].quantity

    send_callback(svc, p, stk_success(p))

    session.expire_all()
    p = session.get(Payment, p.payment_id)
    assert p.status == PaymentStatus.SUCCESSFUL
    assert p.mpesa_receipt_number == "UK5IR0ZYZO"
    assert p.mpesa_merchant_request_id == "m-1"
    assert p.failure_reason is None and not p.needs_review
    assert session.get(type(world["enquiry"]), world["enquiry"].enquiry_id).status == (
        EnquiryStatus.PAID
    )
    listing = session.get(type(world["listing"]), world["listing"].listing_id)
    assert listing.quantity == stock_before - world["enquiry"].quantity
    assert "PAYMENT_RECOVERED" in event_types(session, p.payment_id)


def test_late_success_when_another_attempt_already_paid_is_flagged_for_refund(
    svc, world, mpesa, session
):
    first = wrongly_failed(svc, world, mpesa)
    mpesa.collections.clear()
    fake_request_to_pay = mpesa.request_to_pay

    def second_checkout_id(**kw):
        fake_request_to_pay(**kw)
        mpesa.collections["ws_CO_SECOND"] = mpesa.collections.pop(CHECKOUT_ID)
        return "ws_CO_SECOND"

    mpesa.request_to_pay = second_checkout_id
    second = pay(svc, world)
    mpesa.settle("SUCCESSFUL")
    svc.reconcile_payment(second.payment_id)

    send_callback(svc, first, stk_success(first, receipt="UK5LATE001"))

    session.expire_all()
    first = session.get(Payment, first.payment_id)
    assert first.status == PaymentStatus.FAILED
    assert first.needs_review
    assert "UK5LATE001" in first.review_reason
    assert session.get(Payment, second.payment_id).status == PaymentStatus.SUCCESSFUL


def test_failure_callback_for_a_failed_payment_is_only_logged(
    svc, world, mpesa, session
):
    p = wrongly_failed(svc, world, mpesa)
    body = stk_success(p)
    body["Body"]["stkCallback"]["ResultCode"] = 1032
    body["Body"]["stkCallback"]["ResultDesc"] = "Request cancelled by user"

    send_callback(svc, p, body)

    session.expire_all()
    p = session.get(Payment, p.payment_id)
    assert p.status == PaymentStatus.FAILED and not p.needs_review
    assert "LATE_CALLBACK_FAILED" in event_types(session, p.payment_id)


def test_money_for_a_closed_enquiry_is_flagged_for_refund(svc, world, mpesa, session):
    p = wrongly_failed(svc, world, mpesa)
    world["enquiry"].status = EnquiryStatus.CANCELLED
    world["enquiry"].failure_reason = "PRICE"
    session.commit()

    send_callback(svc, p, stk_success(p))

    session.expire_all()
    p = session.get(Payment, p.payment_id)
    assert p.needs_review and "cancelled" in p.review_reason
    assert not p.stock_deducted
