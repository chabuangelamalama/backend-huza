import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.payment_deps import get_current_user, get_db, get_settings
from routers.payments import router
from services.mpesa import callback_token
from tests.test_payments import PAYER, make_settings, SECRET


@pytest.fixture
def api(session, world):
    state = {"user": world["buyer"]}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    # The configured simulator makes no network calls and never moves real money.
    app.dependency_overrides[get_settings] = lambda: make_settings(
        mode="simulated", simulator_delay_seconds=3600
    )
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    client = TestClient(app)
    return client, state, world


def as_user(api, who):
    client, state, w = api
    state["user"] = w[who]
    return client


def start(api):
    client, state, w = api
    user = state["user"]
    phone = (
        getattr(user, "phone", None)
        or getattr(user, "phone_number", None)
        or PAYER
    )
    return client.post(
        f"/enquiries/{w['enquiry'].enquiry_id}/payments",
        json={"phone_number": phone},
    )


def test_buyer_starts_payment_and_gets_masked_phone(api):
    r = start(api)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "PENDING" and body["phone_number"] == "254****678"
    assert r.headers["cache-control"] == "no-store"


def test_seller_and_outsider_get_404_when_paying(api):
    client, _, w = api
    for who in ("seller", "other"):
        r = as_user(api, who).post(
            f"/enquiries/{w['enquiry'].enquiry_id}/payments",
            json={"phone_number": PAYER},
        )
        assert r.status_code == 404


def test_bad_input_is_rejected(api):
    client, _, w = api
    url = f"/enquiries/{w['enquiry'].enquiry_id}/payments"
    assert client.post(url, json={"phone_number": "12"}).status_code == 422
    assert (
        client.post(url, json={"phone_number": PAYER, "amount": 1}).status_code == 422
    )
    assert (
        client.post(
            "/enquiries/not-a-uuid/payments", json={"phone_number": PAYER}
        ).status_code
        == 422
    )


def test_each_party_sees_its_own_view(api):
    pid = start(api).json()["payment_id"]
    seller = as_user(api, "seller").get(f"/payments/{pid}").json()
    assert "phone_number" not in seller and seller["payout_status"] == "NOT_DUE"
    admin = as_user(api, "admin").get(f"/payments/{pid}").json()
    assert "reference_id" in admin and admin["needs_review"] is False
    assert as_user(api, "other").get(f"/payments/{pid}").status_code == 404


def test_payout_details_route_is_not_mistaken_for_a_payment_id(api):
    r = as_user(api, "seller").get("/payments/payout-details")
    assert r.status_code == 200 and r.json()["payout_phone"] == "254****111"
    r = as_user(api, "seller").put(
        "/payments/payout-details", json={"payout_phone": "0712999000"}
    )
    assert r.status_code == 200 and r.json()["payout_phone"] == "254****000"


def test_lists_by_side(api):
    start(api)
    assert len(as_user(api, "buyer").get("/payments?side=buyer").json()) == 1
    assert len(as_user(api, "seller").get("/payments?side=seller").json()) == 1
    assert as_user(api, "seller").get("/payments?side=buyer").json() == []
    assert as_user(api, "buyer").get("/payments?side=nonsense").status_code == 422


def test_admin_endpoints_need_admin(api):
    client, _, _ = api
    pid = start(api).json()["payment_id"]
    for method, url in (
        ("get", "/admin/payments"),
        ("get", f"/admin/payments/{pid}/events"),
        ("post", "/admin/payments/sweep"),
        ("post", f"/admin/payments/{pid}/reconcile"),
        ("post", f"/admin/payments/{pid}/payout"),
    ):
        assert getattr(as_user(api, "buyer"), method)(url).status_code == 403
    r = as_user(api, "buyer").post(f"/admin/payments/{pid}/refund", json={})
    assert r.status_code == 403
    admin = as_user(api, "admin")
    assert admin.get("/admin/payments").status_code == 200
    assert (
        admin.get(f"/admin/payments/{pid}/events").json()[0]["event_type"]
        == "PAYMENT_CREATED"
    )
    assert admin.post("/admin/payments/sweep").json()["checked"] >= 0


def test_callback_is_accessible_and_needs_no_login(api):
    client, state, w = api
    payment = start(api).json()
    admin_payment = (
        as_user(api, "admin").get(f"/payments/{payment['payment_id']}").json()
    )
    reference = admin_payment["reference_id"]
    token = callback_token(SECRET, "collection", reference)
    state["user"] = None
    url = f"/payments/mpesa/callback/collection/{reference}/{token}"
    assert client.put(url).status_code == 200
    assert client.post(url).status_code == 200
