"""End-to-end tests of the auth endpoints. They need the Postgres test database
from conftest.py and are skipped automatically when it is not available."""

import re
import uuid
from decimal import Decimal

import pytest

from core.security import hash_password
from models import Business, Location, User
from models.business import BusinessRole, BusinessType
from models.location import OsmType
from models.user import UserRole

PASSWORD = "Correct1horse"


def make_admin(session, **changes) -> User:
    values = dict(
        first_name="Diane",
        last_name="Mukamana",
        email=f"{uuid.uuid4().hex}@huza.rw",
        password_hash=hash_password(PASSWORD),
        user_role=UserRole.ADMIN,
    )
    values.update(changes)
    user = User(**values)
    session.add(user)
    session.flush()
    return user


def make_business_user(session, **changes) -> User:
    location = Location(
        osm_type=OsmType.NODE,
        osm_id=uuid.uuid4().int % 10**9,
        name="Westlands",
        display_name="Westlands, Nairobi, Nairobi County, Kenya",
        latitude=Decimal("-1.267500"),
        longitude=Decimal("36.810800"),
        sub_county="Westlands",
        county="Nairobi",
    )
    session.add(location)
    session.flush()
    business = Business(
        business_legal_name="Kigali Timber Works",
        business_role=BusinessRole.SUPPLIER,
        business_type=BusinessType.BUSINESS,
        location_id=location.location_id,
        streams=["SAWDUST"],
        contact_email="info@example.rw",
    )
    session.add(business)
    session.flush()
    values = dict(
        first_name="Jean",
        last_name="Habimana",
        email=f"{uuid.uuid4().hex}@example.rw",
        password_hash=hash_password(PASSWORD),
        business_id=business.business_id,
        user_role=UserRole.BUSINESS_USER,
    )
    values.update(changes)
    user = User(**values)
    session.add(user)
    session.flush()
    return user


def sign_in(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def token_for(client, user):
    return sign_in(client, user.email).json()["access_token"]


def test_login_returns_a_token_and_the_user(client, session):
    user = make_business_user(session)

    response = sign_in(client, user.email)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    assert body["user"]["email"] == user.email
    assert body["user"]["role"] == "BUSINESS_USER"
    assert body["user"]["business"]["approval_status"] == "PENDING"
    assert "password_hash" not in body["user"]


def test_login_ignores_email_case_and_spaces(client, session):
    user = make_business_user(session)
    assert sign_in(client, f"  {user.email.upper()} ").status_code == 200


def test_wrong_password_and_unknown_email_look_identical(client, session):
    user = make_business_user(session)

    wrong_password = sign_in(client, user.email, "Wrong1horse")
    unknown_email = sign_in(client, "nobody@example.rw")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json()["detail"] == "Email or password is incorrect."


def test_the_token_opens_me_and_a_missing_token_does_not(client, session):
    user = make_business_user(session)
    token = token_for(client, user)

    assert client.get("/auth/me", headers=auth_header(token)).status_code == 200
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers=auth_header("garbage")).status_code == 401


def test_the_docs_authorize_form_works(client, session):
    user = make_business_user(session)
    response = client.post(
        "/auth/token", data={"username": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_the_account_locks_after_too_many_failures(client, session):
    user = make_business_user(session)

    for _ in range(3):
        assert sign_in(client, user.email, "Wrong1horse").status_code == 401

    locked = sign_in(client, user.email)
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    assert "Try again" in locked.json()["detail"]


def test_a_successful_login_resets_the_failure_count(client, session):
    user = make_business_user(session)

    for _ in range(2):
        sign_in(client, user.email, "Wrong1horse")
        assert sign_in(client, user.email).status_code == 200

    for _ in range(2):
        assert sign_in(client, user.email, "Wrong1horse").status_code == 401
        assert sign_in(client, user.email).status_code == 200


def test_an_admin_can_unlock_an_account(client, session):
    user = make_business_user(session)
    admin = make_admin(session)
    for _ in range(3):
        sign_in(client, user.email, "Wrong1horse")
    assert sign_in(client, user.email).status_code == 429

    admin_token = token_for(client, admin)
    response = client.post(
        f"/admin/users/{user.user_id}/unlock", headers=auth_header(admin_token)
    )

    assert response.status_code == 200
    assert sign_in(client, user.email).status_code == 200


def test_logout_revokes_the_token(client, session):
    user = make_business_user(session)
    token = token_for(client, user)

    assert client.post("/auth/logout", headers=auth_header(token)).status_code == 204
    assert client.get("/auth/me", headers=auth_header(token)).status_code == 401


def test_change_password_signs_out_old_tokens_and_keeps_this_device(client, session):
    user = make_business_user(session)
    old_token = token_for(client, user)

    response = client.post(
        "/auth/change-password",
        headers=auth_header(old_token),
        json={"current_password": PASSWORD, "new_password": "Brand2newpass"},
    )

    assert response.status_code == 200
    new_token = response.json()["access_token"]
    assert client.get("/auth/me", headers=auth_header(old_token)).status_code == 401
    assert client.get("/auth/me", headers=auth_header(new_token)).status_code == 200
    assert sign_in(client, user.email, PASSWORD).status_code == 401
    assert sign_in(client, user.email, "Brand2newpass").status_code == 200


def test_change_password_needs_the_current_password(client, session):
    user = make_business_user(session)
    token = token_for(client, user)

    response = client.post(
        "/auth/change-password",
        headers=auth_header(token),
        json={"current_password": "Wrong1horse", "new_password": "Brand2newpass"},
    )

    assert response.status_code == 400


@pytest.mark.parametrize("weak", ["short1", "nodigitshere", "x" * 129 + "1"])
def test_weak_new_passwords_are_refused(client, session, weak):
    user = make_business_user(session)
    token = token_for(client, user)

    response = client.post(
        "/auth/change-password",
        headers=auth_header(token),
        json={"current_password": PASSWORD, "new_password": weak},
    )

    assert response.status_code == 400


def reset_code_from(mailer) -> str:
    match = re.search(r"code is: (\d{6})", mailer.sent[-1].text)
    assert match is not None, f"No 6-digit code found in: {mailer.sent[-1].text}"
    return match.group(1)


def test_forgot_password_answers_the_same_for_every_address(client, session, mailer):
    user = make_business_user(session)

    known = client.post("/auth/forgot-password", json={"email": user.email})
    unknown = client.post("/auth/forgot-password", json={"email": "who@example.rw"})

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(mailer.sent) == 1
    assert mailer.sent[0].to == user.email


def test_reset_password_flow_works_once(client, session, mailer):
    user = make_business_user(session)
    old_token = token_for(client, user)
    client.post("/auth/forgot-password", json={"email": user.email})
    code = reset_code_from(mailer)

    done = client.post(
        "/auth/reset-password",
        json={"email": user.email, "code": code, "password": "Reset4success"},
    )

    assert done.status_code == 200
    assert sign_in(client, user.email, "Reset4success").status_code == 200
    assert sign_in(client, user.email, PASSWORD).status_code == 401
    assert client.get("/auth/me", headers=auth_header(old_token)).status_code == 401

    again = client.post(
        "/auth/reset-password",
        json={"email": user.email, "code": code, "password": "Another5pass"},
    )
    assert again.status_code == 400


def test_reset_password_rejects_a_bad_token(client):
    response = client.post(
        "/auth/reset-password",
        json={
            "email": "nobody@example.rw",
            "code": "000000",
            "password": "Reset4success",
        },
    )
    assert response.status_code == 400


def test_reset_password_enforces_the_password_rule(client, session, mailer):
    user = make_business_user(session)
    client.post("/auth/forgot-password", json={"email": user.email})

    response = client.post(
        "/auth/reset-password",
        json={
            "email": user.email,
            "code": reset_code_from(mailer),
            "password": "short",
        },
    )

    assert response.status_code == 400


def test_resetting_a_password_also_clears_a_lockout(client, session, mailer):
    user = make_business_user(session)
    for _ in range(3):
        sign_in(client, user.email, "Wrong1horse")
    client.post("/auth/forgot-password", json={"email": user.email})

    client.post(
        "/auth/reset-password",
        json={
            "email": user.email,
            "code": reset_code_from(mailer),
            "password": "Reset4success",
        },
    )

    assert sign_in(client, user.email, "Reset4success").status_code == 200


def test_admin_routes_need_a_token(client):
    assert client.get("/admin/users").status_code == 401


def test_a_business_user_cannot_use_admin_routes(client, session):
    user = make_business_user(session)
    token = token_for(client, user)
    assert client.get("/admin/users", headers=auth_header(token)).status_code == 403


def test_an_admin_can_list_and_filter_users(client, session):
    admin = make_admin(session)
    make_business_user(session)
    token = token_for(client, admin)

    everyone = client.get("/admin/users", headers=auth_header(token))
    only_admins = client.get(
        "/admin/users", params={"role": "ADMIN"}, headers=auth_header(token)
    )

    assert everyone.status_code == 200
    assert everyone.json()["total"] >= 2
    assert {u["role"] for u in only_admins.json()["items"]} == {"ADMIN"}


def test_unlocking_a_missing_user_is_a_404(client, session):
    admin = make_admin(session)
    token = token_for(client, admin)
    response = client.post(
        f"/admin/users/{uuid.uuid4()}/unlock", headers=auth_header(token)
    )
    assert response.status_code == 404


def test_health_endpoints(client):
    assert client.get("/health").json() == {"status": "ok"}
