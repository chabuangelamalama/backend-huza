import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import create_access_token
from main import app
from models.user import UserRole
from tests.notification_helpers import (
    NotificationEvent,
    make_admin_user,
    make_business_owner,
    make_notification,
    make_open_enquiry,
)

URL = "/notifications"


def headers_for(user):
    token = create_access_token(user.user_id, user.user_role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def admin(session):
    return make_admin_user(session)


@pytest.fixture
def owner(session):
    return make_business_owner(session)


@pytest.fixture
def other_owner(session):
    return make_business_owner(session)


def test_listing_needs_a_login(client):
    assert client.get(URL).status_code == 401


def test_a_bad_token_is_rejected(client):
    response = client.get(URL, headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


def test_an_expired_token_is_rejected(client, owner):
    token = create_access_token(
        owner.user_id, UserRole.BUSINESS_USER, expires_minutes=-5
    )
    response = client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_a_user_sees_only_their_own_notifications(client, session, owner, other_owner):
    mine = make_notification(session, owner)
    make_notification(session, other_owner)
    response = client.get(URL, headers=headers_for(owner))
    assert response.status_code == 200
    assert [item["notification_id"] for item in response.json()] == [
        str(mine.notification_id)
    ]


def test_a_business_that_is_not_approved_can_still_read_its_notifications(
    client, session, owner
):
    make_notification(session, owner, event_type=NotificationEvent.APPROVAL_DECISION)
    response = client.get(URL, headers=headers_for(owner))
    assert response.status_code == 200
    assert response.json()[0]["event_type"] == "APPROVAL_DECISION"


def test_an_admin_sees_only_their_own_notifications_too(client, session, admin, owner):
    make_notification(session, owner)
    mine = make_notification(session, admin)
    response = client.get(URL, headers=headers_for(admin))
    assert [item["notification_id"] for item in response.json()] == [
        str(mine.notification_id)
    ]


def test_a_notification_shows_if_it_is_read(client, session, owner):
    make_notification(session, owner)
    make_notification(session, owner, read_at=datetime.now(timezone.utc))
    response = client.get(URL, headers=headers_for(owner))
    assert sorted(item["is_read"] for item in response.json()) == [False, True]


def test_the_list_can_show_only_unread(client, session, owner):
    unread = make_notification(session, owner)
    make_notification(session, owner, read_at=datetime.now(timezone.utc))
    response = client.get(
        URL, params={"unread_only": "true"}, headers=headers_for(owner)
    )
    assert [item["notification_id"] for item in response.json()] == [
        str(unread.notification_id)
    ]


def test_the_list_can_be_filtered_by_event_type(client, session, owner):
    make_notification(session, owner)
    failed = make_notification(
        session, owner, event_type=NotificationEvent.PAYMENT_FAILED
    )
    response = client.get(
        URL, params={"event_type": "PAYMENT_FAILED"}, headers=headers_for(owner)
    )
    assert [item["notification_id"] for item in response.json()] == [
        str(failed.notification_id)
    ]


def test_an_unknown_event_type_filter_gives_422(client, owner):
    response = client.get(
        URL, params={"event_type": "NOPE"}, headers=headers_for(owner)
    )
    assert response.status_code == 422


@pytest.mark.parametrize("limit", [0, 101])
def test_the_list_limit_must_be_between_1_and_100(client, owner, limit):
    response = client.get(URL, params={"limit": limit}, headers=headers_for(owner))
    assert response.status_code == 422


def test_the_list_offset_cannot_be_negative(client, owner):
    response = client.get(URL, params={"offset": -1}, headers=headers_for(owner))
    assert response.status_code == 422


def test_the_list_can_be_paged(client, session, owner):
    for _ in range(3):
        make_notification(session, owner)
    response = client.get(
        URL, params={"limit": 2, "offset": 2}, headers=headers_for(owner)
    )
    assert len(response.json()) == 1


def test_unread_count_needs_a_login(client):
    assert client.get(f"{URL}/unread-count").status_code == 401


def test_unread_count_counts_only_my_unread(client, session, owner, other_owner):
    make_notification(session, owner)
    make_notification(session, owner)
    make_notification(session, owner, read_at=datetime.now(timezone.utc))
    make_notification(session, other_owner)
    response = client.get(f"{URL}/unread-count", headers=headers_for(owner))
    assert response.status_code == 200
    assert response.json() == {"count": 2}


def test_read_all_marks_only_my_notifications(client, session, owner, other_owner):
    make_notification(session, owner)
    make_notification(session, owner)
    theirs = make_notification(session, other_owner)
    response = client.post(f"{URL}/read-all", headers=headers_for(owner))
    assert response.status_code == 200
    assert response.json() == {"updated": 2}
    count = client.get(f"{URL}/unread-count", headers=headers_for(owner))
    assert count.json() == {"count": 0}
    session.refresh(theirs)
    assert theirs.read_at is None


def test_read_all_with_nothing_unread_updates_zero(client, owner):
    response = client.post(f"{URL}/read-all", headers=headers_for(owner))
    assert response.json() == {"updated": 0}


def test_read_all_needs_a_login(client):
    assert client.post(f"{URL}/read-all").status_code == 401


def test_a_user_can_read_one_of_their_notifications(client, session, owner):
    notification = make_notification(session, owner)
    response = client.get(
        f"{URL}/{notification.notification_id}", headers=headers_for(owner)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["notification_id"] == str(notification.notification_id)
    assert body["is_read"] is False


def test_a_user_cannot_read_someone_elses_notification(
    client, session, owner, other_owner
):
    theirs = make_notification(session, other_owner)
    response = client.get(f"{URL}/{theirs.notification_id}", headers=headers_for(owner))
    assert response.status_code == 404
    assert response.json()["detail"] == "Notification not found."


def test_an_admin_cannot_read_someone_elses_notification(client, session, admin, owner):
    theirs = make_notification(session, owner)
    response = client.get(f"{URL}/{theirs.notification_id}", headers=headers_for(admin))
    assert response.status_code == 404


def test_reading_an_unknown_notification_gives_404(client, owner):
    response = client.get(f"{URL}/{uuid.uuid4()}", headers=headers_for(owner))
    assert response.status_code == 404


def test_reading_a_malformed_id_gives_422(client, owner):
    response = client.get(f"{URL}/not-an-id", headers=headers_for(owner))
    assert response.status_code == 422


def test_an_admin_can_create_a_notification(client, admin, owner):
    body = {"user_id": str(owner.user_id), "event_type": "APPROVAL_DECISION"}
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 201
    created = response.json()
    assert created["user_id"] == str(owner.user_id)
    assert created["event_type"] == "APPROVAL_DECISION"
    assert created["is_read"] is False
    assert created["notification_id"]


def test_a_created_notification_shows_up_for_the_user(client, admin, owner):
    body = {"user_id": str(owner.user_id), "event_type": "PAYOUT_SENT"}
    client.post(URL, json=body, headers=headers_for(admin))
    response = client.get(URL, headers=headers_for(owner))
    assert [item["event_type"] for item in response.json()] == ["PAYOUT_SENT"]


def test_a_notification_can_point_to_an_enquiry_and_a_listing(
    client, session, admin, owner
):
    enquiry = make_open_enquiry(session)
    body = {
        "user_id": str(owner.user_id),
        "event_type": "ENQUIRY_RECEIVED",
        "enquiry_id": str(enquiry.enquiry_id),
        "listing_id": str(enquiry.listing_id),
    }
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 201
    assert response.json()["enquiry_id"] == str(enquiry.enquiry_id)
    assert response.json()["listing_id"] == str(enquiry.listing_id)


def test_a_business_user_cannot_create_a_notification(client, owner):
    body = {"user_id": str(owner.user_id), "event_type": "APPROVAL_DECISION"}
    response = client.post(URL, json=body, headers=headers_for(owner))
    assert response.status_code == 403
    assert "cannot create notifications" in response.json()["detail"]


def test_creating_needs_a_login(client, owner):
    body = {"user_id": str(owner.user_id), "event_type": "APPROVAL_DECISION"}
    assert client.post(URL, json=body).status_code == 401


def test_creating_for_a_user_that_does_not_exist_gives_422(client, admin):
    body = {"user_id": str(uuid.uuid4()), "event_type": "APPROVAL_DECISION"}
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 422
    assert response.json()["detail"] == "The user, enquiry or listing does not exist."


def test_creating_with_an_unknown_enquiry_gives_422(client, admin, owner):
    body = {
        "user_id": str(owner.user_id),
        "event_type": "ENQUIRY_RECEIVED",
        "enquiry_id": str(uuid.uuid4()),
    }
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 422


def test_creating_without_a_user_gives_422(client, admin):
    response = client.post(
        URL, json={"event_type": "PAYOUT_SENT"}, headers=headers_for(admin)
    )
    assert response.status_code == 422


def test_creating_with_an_unknown_event_type_gives_422(client, admin, owner):
    body = {"user_id": str(owner.user_id), "event_type": "NOPE"}
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 422


def test_creating_with_an_unknown_field_gives_422(client, admin, owner):
    body = {
        "user_id": str(owner.user_id),
        "event_type": "PAYOUT_SENT",
        "colour": "red",
    }
    response = client.post(URL, json=body, headers=headers_for(admin))
    assert response.status_code == 422


def test_a_user_can_mark_their_notification_as_read(client, session, owner):
    notification = make_notification(session, owner)
    response = client.patch(
        f"{URL}/{notification.notification_id}/read", headers=headers_for(owner)
    )
    assert response.status_code == 200
    assert response.json()["is_read"] is True
    assert response.json()["read_at"] is not None


def test_marking_as_read_twice_keeps_the_first_time(client, session, owner):
    notification = make_notification(session, owner)
    path = f"{URL}/{notification.notification_id}/read"
    first = client.patch(path, headers=headers_for(owner))
    second = client.patch(path, headers=headers_for(owner))
    assert first.json()["read_at"] == second.json()["read_at"]


def test_a_user_cannot_mark_someone_elses_notification_as_read(
    client, session, owner, other_owner
):
    theirs = make_notification(session, other_owner)
    response = client.patch(
        f"{URL}/{theirs.notification_id}/read", headers=headers_for(owner)
    )
    assert response.status_code == 404
    session.refresh(theirs)
    assert theirs.read_at is None


def test_marking_an_unknown_notification_as_read_gives_404(client, owner):
    response = client.patch(f"{URL}/{uuid.uuid4()}/read", headers=headers_for(owner))
    assert response.status_code == 404


def test_marking_as_read_needs_a_login(client, session, owner):
    notification = make_notification(session, owner)
    response = client.patch(f"{URL}/{notification.notification_id}/read")
    assert response.status_code == 401


def test_a_user_can_delete_their_notification(client, session, owner):
    notification = make_notification(session, owner)
    path = f"{URL}/{notification.notification_id}"
    response = client.delete(path, headers=headers_for(owner))
    assert response.status_code == 204
    again = client.get(path, headers=headers_for(owner))
    assert again.status_code == 404


def test_a_user_cannot_delete_someone_elses_notification(
    client, session, owner, other_owner
):
    theirs = make_notification(session, other_owner)
    response = client.delete(
        f"{URL}/{theirs.notification_id}", headers=headers_for(owner)
    )
    assert response.status_code == 404
    still_there = client.get(
        f"{URL}/{theirs.notification_id}", headers=headers_for(other_owner)
    )
    assert still_there.status_code == 200


def test_deleting_an_unknown_notification_gives_404(client, owner):
    response = client.delete(f"{URL}/{uuid.uuid4()}", headers=headers_for(owner))
    assert response.status_code == 404


def test_deleting_needs_a_login(client, session, owner):
    notification = make_notification(session, owner)
    response = client.delete(f"{URL}/{notification.notification_id}")
    assert response.status_code == 401
