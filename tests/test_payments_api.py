"""HTTP-level tests: routes, status codes and what each caller can see.
Authentication is replaced by a dependency override, MTN by FakeMomo."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.payment_deps import get_current_user, get_db, get_momo_client, get_settings
from routers.payments import router
from services.momo import callback_token
from tests.test_payments import PAYER, SECRET, FakeMomo, make_settings, world  # noqa: F401


@pytest.fixture
def api(session, world):  # noqa: F811
    momo = FakeMomo()
    state = {"user": world["buyer"]}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_momo_client] = lambda: momo
    app.dependency_overrides[get_settings] = lambda: make_settings()
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    client = TestClient(app)
    return client, state, momo, world


def as_user(api, who):
    client, state, _, w = api
    state["user"] = w[who]
    return client


def start(api):
    client, _, _, w = api
    return client.post(
        f"/enquiries/{w['enquiry'].enquiry_id}/payments",
        json={"payer_phone": "0788123456"},
    )


def test_buyer_starts_payment_and_gets_masked_phone(api):
    r = start(api)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "PENDING" and body["payer_phone"] == "250****456"
    assert r.headers["cache-control"] == "no-store"


def test_seller_and_outsider_get_404_when_paying(api):
    for who in ("seller", "other"):
        r = as_user(api, who).post(
            f"/enquiries/{api[3]['enquiry'].enquiry_id}/payments",
            json={"payer_phone": PAYER},
        )
        assert r.status_code == 404


def test_bad_input_is_rejected(api):
    client, _, _, w = api
    url = f"/enquiries/{w['enquiry'].enquiry_id}/payments"
    assert client.post(url, json={"payer_phone": "12"}).status_code == 422
    assert client.post(url, json={"payer_phone": PAYER, "amount": 1}).status_code == 422
    assert (
        client.post(
            "/enquiries/not-a-uuid/payments", json={"payer_phone": PAYER}
        ).status_code
        == 422
    )


def test_each_party_sees_its_own_view(api):
    pid = start(api).json()["payment_id"]
    seller = as_user(api, "seller").get(f"/payments/{pid}").json()
    assert "payer_phone" not in seller and seller["payout_status"] == "NOT_DUE"
    admin = as_user(api, "admin").get(f"/payments/{pid}").json()
    assert "reference_id" in admin and admin["needs_review"] is False
    assert as_user(api, "other").get(f"/payments/{pid}").status_code == 404


def test_payout_details_route_is_not_mistaken_for_a_payment_id(api):
    r = as_user(api, "seller").get("/payments/payout-details")
    assert r.status_code == 200 and r.json()["payout_phone"] == "250****111"
    r = as_user(api, "seller").put(
        "/payments/payout-details", json={"payout_phone": "0788999000"}
    )
    assert r.status_code == 200 and r.json()["payout_phone"] == "250****000"


def test_lists_by_side(api):
    start(api)
    assert len(as_user(api, "buyer").get("/payments?side=buyer").json()) == 1
    assert len(as_user(api, "seller").get("/payments?side=seller").json()) == 1
    assert as_user(api, "seller").get("/payments?side=buyer").json() == []
    assert as_user(api, "buyer").get("/payments?side=nonsense").status_code == 422


def test_confirm_receipt_flow_over_http(api):
    client, _, momo, w = api
    pid = start(api).json()["payment_id"]
    momo.settle("SUCCESSFUL")
    assert (
        as_user(api, "buyer").get(f"/payments/{pid}").json()["status"] == "SUCCESSFUL"
    )
    r = as_user(api, "buyer").post(
        f"/enquiries/{w['enquiry'].enquiry_id}/confirm-receipt"
    )
    assert r.status_code == 200
    assert len(momo.payouts()) == 1


def test_admin_endpoints_need_admin(api):
    client, _, _, _ = api
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


def test_callback_is_signed_and_needs_no_login(api):
    client, state, _, _ = api
    r = start(api).json()
    ref = api[2].collections and next(iter(api[2].collections))
    state["user"] = None  # callback must not depend on a logged-in user
    url = "/payments/momo/callback/collection/{}/{}"
    assert client.put(url.format(ref, "wrong")).status_code == 404
    assert (
        client.put(
            url.format(ref, callback_token(SECRET, "collection", ref))
        ).status_code
        == 200
    )
    assert (
        client.post(
            url.format(ref, callback_token(SECRET, "collection", ref))
        ).status_code
        == 200
    )
    assert r["status"] == "PENDING"


def test_without_real_auth_wired_everything_answers_501(session, world):  # noqa: F811
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_momo_client] = lambda: FakeMomo()
    app.dependency_overrides[get_settings] = lambda: make_settings()
    r = TestClient(app).get("/payments")
    assert r.status_code == 501
