import json
from decimal import Decimal

import httpx
import pytest

from core.payment_config import MpesaSettings
from models.business import PayoutNetwork
from routers.payments import PayoutDetailsRequest
from schemas.payment import InitiatePaymentRequest, normalize_msisdn
from services.money import compute_total, split_fee, whole_kes
from services.mpesa import (
    MpesaClient,
    MpesaRejected,
    MpesaTransient,
    callback_token,
    to_mpesa_amount,
    verify_callback_token,
)


SECRET = "s" * 40
REF = "11111111-1111-1111-1111-111111111111"
CHECKOUT_ID = "ws_CO_28102026165942123"


def settings(**kw) -> MpesaSettings:
    base = dict(
        base_url="https://sandbox.safaricom.co.ke",
        currency="KES",
        consumer_key="key",
        consumer_secret="secret",
        express_shortcode="174379",
        express_passkey="passkey",
        callback_base_url="https://api.huza.ke",
        callback_secret=SECRET,
    )
    base.update(kw)
    return MpesaSettings(**base)


def client_for(handler) -> MpesaClient:
    http = httpx.Client(
        base_url="https://sandbox.safaricom.co.ke",
        transport=httpx.MockTransport(handler),
    )
    return MpesaClient(settings(), http)


def test_total_is_rounded_half_up_to_whole_kes():
    assert compute_total(Decimal("2.5"), Decimal("33.3333")) == Decimal("83")
    assert compute_total(Decimal("100"), Decimal("50")) == Decimal("5000")
    assert whole_kes(Decimal("0.5")) == Decimal("1")


def test_fee_split_adds_up_and_never_zeroes_the_seller():
    fee, payout = split_fee(Decimal("5000"), Decimal("5"))
    assert (fee, payout) == (Decimal("250"), Decimal("4750"))
    fee, payout = split_fee(Decimal("5000"), Decimal("0"))
    assert (fee, payout) == (Decimal("0"), Decimal("5000"))
    fee, payout = split_fee(Decimal("1"), Decimal("50"))
    assert payout >= 1 and fee + payout == 1


def test_fractional_kes_is_refused():
    assert to_mpesa_amount(Decimal("5000.0000")) == "5000"
    with pytest.raises(ValueError):
        to_mpesa_amount(Decimal("5000.50"))
    with pytest.raises(ValueError):
        to_mpesa_amount(Decimal("0"))


@pytest.mark.parametrize(
    "raw", ["0712345678", "+254 712 345 678", "254712345678", "712345678"]
)
def test_phone_normalisation(raw):
    assert normalize_msisdn(raw) == "254712345678"


@pytest.mark.parametrize("raw", ["011234567", "12345", "254712abc678", "071234567"])
def test_bad_phone_rejected(raw):
    with pytest.raises(ValueError):
        normalize_msisdn(raw)


def test_unknown_request_fields_are_rejected():
    with pytest.raises(ValueError):
        InitiatePaymentRequest(phone_number="0712345678", amount=1)


def test_production_settings_are_strict():
    with pytest.raises(ValueError):
        MpesaSettings(environment="production")


def test_callback_token_is_bound_to_kind_and_reference():
    t = callback_token(SECRET, "collection", REF)
    assert verify_callback_token(SECRET, "collection", REF, t)
    assert not verify_callback_token(SECRET, "disbursement", REF, t)
    assert not verify_callback_token(SECRET, "collection", REF.replace("1", "2"), t)
    assert not verify_callback_token("", "collection", REF, t)


def test_request_to_pay_sends_what_mpesa_expects_and_caches_the_token():
    seen = {"token_calls": 0, "pay": None}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v1/generate":
            seen["token_calls"] += 1
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if request.url.path == "/mpesa/stkpush/v1/processrequest":
            seen["pay"] = request
            return httpx.Response(
                200,
                json={
                    "ResponseCode": "0",
                    "CheckoutRequestID": CHECKOUT_ID,
                    "ResponseDescription": "Success",
                },
            )
        return httpx.Response(404)

    c = client_for(handler)
    for _ in range(2):
        res = c.request_to_pay(
            reference_id=REF,
            amount=Decimal("5000"),
            phone_number="254712345678",
            account_reference="Enquiry123",
            transaction_desc="Payment",
        )
        assert res == CHECKOUT_ID

    req = seen["pay"]
    assert seen["token_calls"] == 1
    assert req.headers["Authorization"] == "Bearer tok"
    body = req.content.decode()
    assert '"Amount":"5000"' in body
    assert '"PartyA":"254712345678"' in body
    assert '"BusinessShortCode":"174379"' in body


def _client_with(pay_response: httpx.Response) -> MpesaClient:
    def handler(request):
        if request.url.path.endswith("/generate"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return pay_response

    return client_for(handler)


def _pay(c):
    c.request_to_pay(
        reference_id=REF,
        amount=Decimal("100"),
        phone_number="254712345678",
        account_reference="Ref",
        transaction_desc="Desc",
    )


def test_client_errors_are_rejections_with_a_reason():
    with pytest.raises(MpesaRejected) as e:
        _pay(
            _client_with(
                httpx.Response(
                    200,
                    json={
                        "ResponseCode": "1",
                        "ResponseDescription": "Invalid Parameter",
                    },
                )
            )
        )
    assert "Invalid Parameter" in str(e.value.reason)


@pytest.mark.parametrize("code", [500, 503, 429])
def test_server_errors_are_unknown_outcomes(code):
    with pytest.raises(MpesaTransient):
        _pay(_client_with(httpx.Response(code)))


def test_network_failure_is_an_unknown_outcome():
    def handler(request):
        if request.url.path.endswith("/generate"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        raise httpx.ConnectTimeout("boom")

    with pytest.raises(MpesaTransient):
        _pay(client_for(handler))


def test_status_read_parses_success_and_handles_404():
    def make(resp):
        def handler(request):
            if request.url.path.endswith("/generate"):
                return httpx.Response(
                    200, json={"access_token": "t", "expires_in": 3600}
                )
            return resp

        return client_for(handler)

    ok = make(
        httpx.Response(
            200,
            json={
                "ResultCode": "0",
                "ResultDesc": "The service request has been accepted successfully.",
            },
        )
    ).get_request_to_pay(CHECKOUT_ID)
    assert ok.status == "SUCCESSFUL"
    assert ok.external_id == CHECKOUT_ID

    failed = make(
        httpx.Response(
            200, json={"ResultCode": "1032", "ResultDesc": "Request cancelled by user"}
        )
    ).get_request_to_pay(CHECKOUT_ID)
    assert failed.status == "FAILED"
    assert "cancelled" in failed.reason

    assert make(httpx.Response(404)).get_request_to_pay(CHECKOUT_ID) is None


def test_status_read_uses_the_daraja_stk_query_path():
    seen = []

    def handler(request):
        if request.url.path.endswith("/generate"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        seen.append(request.url.path)
        if request.url.path != "/mpesa/stkpushquery/v1/query":
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "ResultCode": "1037",
                "ResultDesc": "DS timeout user cannot be reached",
            },
        )

    result = client_for(handler).get_request_to_pay(CHECKOUT_ID)

    assert seen == ["/mpesa/stkpushquery/v1/query"]
    assert result.status == "FAILED" and result.result_code == 1037


B2C = dict(
    b2c_shortcode="600999",
    initiator_name="huza-initiator",
    security_credential="encrypted-credential",
)


def _b2c_client(handler, **overrides) -> MpesaClient:
    http = httpx.Client(
        base_url="https://sandbox.safaricom.co.ke",
        transport=httpx.MockTransport(handler),
    )
    return MpesaClient(settings(**{**B2C, **overrides}), http)


def _transfer(c):
    return c.transfer(
        reference_id=REF,
        amount=Decimal("4750"),
        phone_number="254712000111",
        remarks="Payout 11111111",
    )


def test_transfer_sends_the_configured_b2c_credentials():
    seen = {}

    def handler(request):
        if request.url.path.endswith("/generate"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"ResponseCode": "0", "ConversationID": "AG_2026_conv"}
        )

    assert _transfer(_b2c_client(handler)) == "AG_2026_conv"
    body = seen["body"]
    assert body["InitiatorName"] == "huza-initiator"
    assert body["SecurityCredential"] == "encrypted-credential"
    assert body["PartyA"] == "600999"
    assert body["PartyB"] == "254712000111"
    assert body["Amount"] == "4750"
    assert body["ResultURL"] == body["QueueTimeOutURL"]
    assert body["ResultURL"].startswith(
        f"https://api.huza.ke/payments/mpesa/callback/disbursement/{REF}/"
    )


@pytest.mark.parametrize("missing", sorted(B2C))
def test_transfer_without_b2c_settings_is_rejected_before_calling_daraja(missing):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})

    with pytest.raises(MpesaRejected) as e:
        _transfer(_b2c_client(handler, **{missing: ""}))
    assert f"MPESA_{missing.upper()}" in str(e.value)
    assert "/mpesa/b2c/v1/paymentrequest" not in calls


def test_transfer_rejection_carries_the_daraja_reason():
    def handler(request):
        if request.url.path.endswith("/generate"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(400, json={"errorMessage": "Invalid Initiator"})

    with pytest.raises(MpesaRejected) as e:
        _transfer(_b2c_client(handler))
    assert "Invalid Initiator" in str(e.value)


def test_payout_details_default_to_mpesa_and_reject_other_networks():
    body = PayoutDetailsRequest(payout_phone="0712345678")
    assert body.payout_phone == "254712345678"
    assert body.payout_network == PayoutNetwork.MPESA
    with pytest.raises(ValueError):
        PayoutDetailsRequest(payout_phone="0712345678", payout_network="AIRTEL")
