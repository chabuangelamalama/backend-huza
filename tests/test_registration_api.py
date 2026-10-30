"""Registration, email verification and business editing.

The first block needs no database. The rest need the Postgres test database from
conftest.py and are skipped automatically when it is not available."""

import re
import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from models import Location, User
from models.business import ApprovalStatus
from schemas.registration import RegisterRequest
from services.registration_service import manual_osm_id
from tests.test_auth_api import (  # noqa: F401  (fixtures)
    PASSWORD,
    auth_header,
     client,
    mailer,
    make_admin,
    sign_in,
)


def payload(**changes) -> dict:
    body = {
        "first_name": "Aline",
        "last_name": "Uwase",
        "email": "aline@inzozi.rw",
        "phone": "+250788340221",
        "password": PASSWORD,
        "business_role": "SUPPLIER",
        "business": {
            "business_legal_name": "Inzozi Ltd",
            "business_type": "BUSINESS",
            "supplier_kind": "COLLECTOR",
            "streams": ["SAWDUST"],
        },
        "location": {
            "name": "Remera Market",
            "display_name": "Remera Market, Gasabo, Kigali City, Rwanda",
            "latitude": -1.9577,
            "longitude": 30.1127,
            "district": "Gasabo",
            "province": "Kigali City",
        },
    }
    body.update(changes)
    return body


def code_from(mailer) -> str:
    match = re.search(r"code is: (\d{6})", mailer.sent[-1].text)
    assert match is not None, f"No 6-digit code found in: {mailer.sent[-1].text}"
    return match.group(1)


def register(client, **changes):
    return client.post("/auth/register", json=payload(**changes))


def test_the_request_rules_match_the_database_rules():
    with pytest.raises(ValidationError):
        RegisterRequest(**payload(password="short1"))
    with pytest.raises(ValidationError):
        RegisterRequest(**payload(password="nodigitshere"))
    with pytest.raises(ValidationError):
        RegisterRequest(**payload(business_role="BUYER"))
    bad_consumer = payload()
    bad_consumer["business"]["business_type"] = "CONSUMER"
    with pytest.raises(ValidationError):
        RegisterRequest(**bad_consumer)
    no_streams = payload()
    no_streams["business"]["streams"] = []
    with pytest.raises(ValidationError):
        RegisterRequest(**no_streams)
    half_osm = payload()
    half_osm["location"]["osm_type"] = "NODE"
    with pytest.raises(ValidationError):
        RegisterRequest(**half_osm)


def test_a_manual_place_gets_the_same_negative_id_every_time():
    a = manual_osm_id(Decimal("-1.957700"), Decimal("30.112700"))
    b = manual_osm_id(Decimal("-1.957700"), Decimal("30.112700"))
    c = manual_osm_id(Decimal("-1.957800"), Decimal("30.112700"))
    assert a == b < 0
    assert a != c


# --------------------------------------------------------------------------- #
# Register
# --------------------------------------------------------------------------- #


def test_register_creates_a_pending_business_and_signs_the_user_in(
    client, session, mailer
):
    response = register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    user = body["user"]
    assert user["email"] == "aline@inzozi.rw"
    assert user["role"] == "BUSINESS_USER"
    assert user["email_verified"] is False
    assert user["business"]["approval_status"] == "PENDING"
    assert user["business"]["business_role"] == "SUPPLIER"

    me = client.get("/auth/me", headers=auth_header(body["access_token"]))
    assert me.status_code == 200
    assert sign_in(client, "aline@inzozi.rw").status_code == 200

    assert len(mailer.sent) == 1
    assert mailer.sent[0].to == "aline@inzozi.rw"


def test_the_same_email_cannot_register_twice(client, session):
    assert register(client).status_code == 201
    again = register(client, email="  ALINE@inzozi.rw ")
    assert again.status_code == 409


def test_bad_registrations_are_refused(client, session):
    assert register(client, password="short").status_code == 422
    assert register(client, email="not-an-email").status_code == 422


def test_two_businesses_in_the_same_place_share_one_location(client, session):
    register(client)
    register(client, email="second@inzozi.rw")

    places = session.query(Location).filter(Location.name == "Remera Market").all()
    assert len(places) == 1


# --------------------------------------------------------------------------- #
# Email verification
# --------------------------------------------------------------------------- #


def test_verify_email_with_the_emailed_code(client, session, mailer):
    token = register(client).json()["access_token"]
    code = code_from(mailer)
    wrong = "000000" if code != "000000" else "111111"

    assert (
        client.post(
            "/auth/verify-email", json={"code": wrong}, headers=auth_header(token)
        ).status_code
        == 400
    )
    done = client.post(
        "/auth/verify-email", json={"code": code}, headers=auth_header(token)
    )
    assert done.status_code == 200
    assert done.json()["email_verified"] is True

    again = client.post(
        "/auth/verify-email", json={"code": code}, headers=auth_header(token)
    )
    assert again.status_code == 200


def test_verify_email_needs_a_signed_in_user(client):
    assert client.post("/auth/verify-email", json={"code": "123456"}).status_code == 401


def test_resend_sends_a_new_code_and_the_old_one_stops_working(client, session, mailer):
    token = register(client).json()["access_token"]
    first = code_from(mailer)

    resend = client.post("/auth/resend-verification", headers=auth_header(token))
    assert resend.status_code == 202
    assert len(mailer.sent) == 2
    second = code_from(mailer)

    if first != second:
        stale = client.post(
            "/auth/verify-email", json={"code": first}, headers=auth_header(token)
        )
        assert stale.status_code == 400
    ok = client.post(
        "/auth/verify-email", json={"code": second}, headers=auth_header(token)
    )
    assert ok.status_code == 200


def test_resend_does_nothing_once_verified(client, session, mailer):
    token = register(client).json()["access_token"]
    client.post(
        "/auth/verify-email",
        json={"code": code_from(mailer)},
        headers=auth_header(token),
    )
    sent_before = len(mailer.sent)

    resend = client.post("/auth/resend-verification", headers=auth_header(token))

    assert resend.status_code == 202
    assert len(mailer.sent) == sent_before


# --------------------------------------------------------------------------- #
# Business details
# --------------------------------------------------------------------------- #


def business_of(session, response) -> User:
    return session.get(User, uuid.UUID(response.json()["user"]["id"]))


def test_a_pending_business_can_be_read_and_edited(client, session):
    token = register(client).json()["access_token"]
    headers = auth_header(token)

    shown = client.get("/business/me", headers=headers)
    assert shown.status_code == 200
    assert shown.json()["business_legal_name"] == "Inzozi Ltd"
    assert shown.json()["location"]["district"] == "Gasabo"

    edited = client.patch(
        "/business/me",
        json={"business_legal_name": "Inzozi Timber", "streams": ["SAWDUST", "GLASS"]},
        headers=headers,
    )
    assert edited.status_code == 200
    assert edited.json()["business_legal_name"] == "Inzozi Timber"
    assert edited.json()["streams"] == ["SAWDUST", "GLASS"]
    assert edited.json()["approval_status"] == "PENDING"


def test_saving_a_rejected_business_sends_it_back_for_review(client, session):
    response = register(client)
    headers = auth_header(response.json()["access_token"])
    business = business_of(session, response).business
    business.approval_status = ApprovalStatus.REJECTED
    business.rejection_reason = "Registration number is missing."
    session.flush()

    edited = client.patch(
        "/business/me", json={"registration_number": "TIN-123456"}, headers=headers
    )

    assert edited.status_code == 200
    assert edited.json()["approval_status"] == "PENDING"
    assert edited.json()["rejection_reason"] is None


def test_an_approved_business_cannot_be_edited_here(client, session):
    response = register(client)
    headers = auth_header(response.json()["access_token"])
    business_of(session, response).business.approval_status = ApprovalStatus.APPROVED
    session.flush()

    edited = client.patch("/business/me", json={"display_name": "New"}, headers=headers)

    assert edited.status_code == 409


def test_the_login_answer_shows_why_a_business_was_rejected(client, session):
    response = register(client)
    business = business_of(session, response).business
    business.approval_status = ApprovalStatus.REJECTED
    business.rejection_reason = "Registration number is missing."
    session.flush()

    shown = sign_in(client, "aline@inzozi.rw").json()["user"]["business"]

    assert shown["approval_status"] == "REJECTED"
    assert shown["rejection_reason"] == "Registration number is missing."


def test_business_routes_need_a_token_and_a_business(client, session):
    assert client.get("/business/me").status_code == 401

    admin = make_admin(session)
    token = sign_in(client, admin.email).json()["access_token"]
    assert client.get("/business/me", headers=auth_header(token)).status_code == 404
