from decimal import Decimal
import httpx
import pytest

from core.payment_config import MomoSettings
from schemas.payment import InitiatePaymentRequest, normalize_msisdn
from services.money import compute_total, split_fee, whole_rwf
from services.momo import (
    MomoClient,
    MomoRejected,
    MomoTransient,
    callback_token,
    to_momo_amount,
    verify_callback_token,
)


SECRET = "s" * 40
REF = "11111111-1111-1111-1111-111111111111"


def settings(**kw) -> MomoSettings:
    base = dict(
        base_url="https://momo.test",
        currency="RWF",
        collection_subscription_key="sub",
        collection_api_user="user",
        collection_api_key="key",
        disbursement_subscription_key="dsub",
        disbursement_api_user="duser",
        disbursement_api_key="dkey",
        callback_base_url="https://api.huza.rw",
        callback_secret=SECRET,
    )
    base.update(kw)
    return MomoSettings(**base)


def client_for(handler) -> MomoClient:
    http = httpx.Client(
        base_url="https://momo.test", transport=httpx.MockTransport(handler)
    )
    return MomoClient(settings(), http)


# ------------------------------------------------------------------ money
def test_total_is_rounded_half_up_to_whole_rwf():
    assert compute_total(Decimal("2.5"), Decimal("33.3333")) == Decimal("83")
    assert compute_total(Decimal("100"), Decimal("50")) == Decimal("5000")
    assert whole_rwf(Decimal("0.5")) == Decimal("1")


def test_fee_split_adds_up_and_never_zeroes_the_seller():
    fee, payout = split_fee(Decimal("5000"), Decimal("5"))
    assert (fee, payout) == (Decimal("250"), Decimal("4750"))
    fee, payout = split_fee(Decimal("5000"), Decimal("0"))
    assert (fee, payout) == (Decimal("0"), Decimal("5000"))
    fee, payout = split_fee(Decimal("1"), Decimal("50"))
    assert payout >= 1 and fee + payout == 1


def test_fractional_rwf_is_refused():
    assert to_momo_amount(Decimal("5000.0000")) == "5000"
    with pytest.raises(ValueError):
        to_momo_amount(Decimal("5000.50"))
    with pytest.raises(ValueError):
        to_momo_amount(Decimal("0"))


# ------------------------------------------------------------------ phones
@pytest.mark.parametrize("raw", ["0788123456", "+250 788 123 456", "250788123456"])
def test_phone_normalisation(raw):
    assert normalize_msisdn(raw) == "250788123456"


@pytest.mark.parametrize("raw", ["0721234567", "12345", "250788abc456", "078812345"])
def test_bad_phone_rejected(raw):
    with pytest.raises(ValueError):
        normalize_msisdn(raw)


def test_unknown_request_fields_are_rejected():
    with pytest.raises(ValueError):
        InitiatePaymentRequest(payer_phone="0788123456", amount=1)


# ---------------------------------------------------------------- settings
def test_production_settings_are_strict():
    with pytest.raises(ValueError):
        MomoSettings(environment="production")


# Removed: test_simulator_is_refused_in_production since simulation blocks are gone


# ---------------------------------------------------------- callback tokens
def test_callback_token_is_bound_to_kind_and_reference():
    t = callback_token(SECRET, "collection", REF)
    assert verify_callback_token(SECRET, "collection", REF, t)
    assert not verify_callback_token(SECRET, "disbursement", REF, t)
    assert not verify_callback_token(SECRET, "collection", REF.replace("1", "2"), t)
    assert not verify_callback_token("", "collection", REF, t)


# ------------------------------------------------------------ MTN HTTP client
def test_request_to_pay_sends_what_mtn_expects_and_caches_the_token():
    seen = {"token_calls": 0, "pay": None}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/collection/token/":
            seen["token_calls"] += 1
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if request.url.path == "/collection/v1_0/requesttopay":
            seen["pay"] = request
            return httpx.Response(202)
        return httpx.Response(404)

    c = client_for(handler)
    for _ in range(2):
        c.request_to_pay(
            reference_id=REF,
            amount=Decimal("5000"),
            payer_msisdn="250788123456",
            external_id="pay-1",
            payer_message="HUZA payment",
            payee_note="note",
        )
    req = seen["pay"]
    assert seen["token_calls"] == 1
    assert req.headers["Authorization"] == "Bearer tok"
    assert req.headers["X-Reference-Id"] == REF
    assert req.headers["Ocp-Apim-Subscription-Key"] == "sub"
    assert req.headers["X-Callback-Url"].startswith(
        f"https://api.huza.rw/payments/momo/callback/collection/{REF}/"
    )
    body = req.content.decode()
    assert '"amount":"5000"' in body.replace(" ", "")
    assert '"currency":"RWF"' in body.replace(" ", "")


def _client_with(pay_response: httpx.Response) -> MomoClient:
    def handler(request):
        if request.url.path.endswith("/token/"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return pay_response

    return client_for(handler)


def _pay(c):
    c.request_to_pay(
        reference_id=REF,
        amount=Decimal("100"),
        payer_msisdn="250788123456",
        external_id="x",
        payer_message="m",
        payee_note="n",
    )


def test_duplicate_reference_is_treated_as_accepted():
    _pay(_client_with(httpx.Response(409)))


def test_client_errors_are_rejections_with_a_reason():
    with pytest.raises(MomoRejected) as e:
        _pay(_client_with(httpx.Response(400, json={"code": "PAYER_NOT_FOUND"})))
    assert e.value.reason == "PAYER_NOT_FOUND"


@pytest.mark.parametrize("code", [500, 503, 429])
def test_server_errors_are_unknown_outcomes(code):
    with pytest.raises(MomoTransient):
        _pay(_client_with(httpx.Response(code)))


def test_network_failure_is_an_unknown_outcome():
    def handler(request):
        if request.url.path.endswith("/token/"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        raise httpx.ConnectTimeout("boom")

    with pytest.raises(MomoTransient):
        _pay(client_for(handler))


def test_status_read_parses_success_and_handles_404_and_garbage():
    def make(resp):
        def handler(request):
            if request.url.path.endswith("/token/"):
                return httpx.Response(
                    200, json={"access_token": "t", "expires_in": 3600}
                )
            return resp

        return client_for(handler)

    ok = make(
        httpx.Response(
            200,
            json={
                "status": "SUCCESSFUL",
                "amount": "5000",
                "currency": "RWF",
                "externalId": "pay-1",
                "financialTransactionId": 987,
            },
        )
    ).get_request_to_pay(REF)
    assert ok.status == "SUCCESSFUL" and ok.amount == Decimal("5000")
    assert ok.financial_transaction_id == "987"

    failed = make(
        httpx.Response(200, json={"status": "FAILED", "reason": {"code": "EXPIRED"}})
    ).get_request_to_pay(REF)
    assert failed.reason == "EXPIRED"

    assert make(httpx.Response(404)).get_request_to_pay(REF) is None
    with pytest.raises(MomoTransient):
        make(httpx.Response(200, json={"status": "WEIRD"})).get_request_to_pay(REF)


def test_reference_in_url_must_be_a_uuid():
    c = client_for(lambda r: httpx.Response(200))
    with pytest.raises(ValueError):
        c.get_request_to_pay("../../admin")
