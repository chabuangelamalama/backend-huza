import uuid
import pytest
import services.notification as service_module
from models.notification import NotificationEvent, Notification
from models.user import UserRole
from tests.test_models import (
    make_business,
    make_listing,
    make_location,
    make_notification,
    make_open_enquiry,
    make_user,
)
from datetime import datetime, timezone
from pydantic import ValidationError
from schemas.notification import (
    NotificationCreate,
    NotificationRead,
    UnreadCount,
    UpdatedCount,
)
from sqlalchemy.exc import IntegrityError
from repositories.notification import notification_repository
from types import SimpleNamespace
from fastapi import HTTPException
from services.notification import notification_service
from fastapi.testclient import TestClient
from database import get_db
from core.security import create_access_token
from main import app


__all__ = [
    "NotificationEvent",
    "make_admin_user",
    "make_business_owner",
    "make_listing",
    "make_notification",
    "make_open_enquiry",
]


def make_admin_user(session):
    return make_user(session, role=UserRole.ADMIN)


def make_business_owner(session):
    location = make_location(session, osm_id=uuid.uuid4().int % 10**9)
    business = make_business(session, location)
    return make_user(session, business)


def payload(**changes):
    values = {
        "user_id": uuid.uuid4(),
        "event_type": NotificationEvent.ENQUIRY_RECEIVED,
    }
    values.update(changes)
    return values


def saved_notification(**changes):
    values = {
        "notification_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "event_type": NotificationEvent.PAYOUT_SENT,
        "enquiry_id": None,
        "listing_id": None,
        "read_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    values.update(changes)
    return Notification(**values)


def test_create_works_with_only_a_user_and_an_event():
    data = NotificationCreate(**payload())
    assert data.enquiry_id is None
    assert data.listing_id is None


def test_create_accepts_an_enquiry_and_a_listing():
    enquiry_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    data = NotificationCreate(**payload(enquiry_id=enquiry_id, listing_id=listing_id))
    assert data.enquiry_id == enquiry_id
    assert data.listing_id == listing_id


def test_create_reads_ids_and_events_sent_as_text():
    user_id = uuid.uuid4()
    data = NotificationCreate(user_id=str(user_id), event_type="PAYMENT_FAILED")
    assert data.user_id == user_id
    assert data.event_type == NotificationEvent.PAYMENT_FAILED


@pytest.mark.parametrize("event", list(NotificationEvent))
def test_create_accepts_every_event_type(event):
    assert NotificationCreate(**payload(event_type=event)).event_type == event


@pytest.mark.parametrize("missing", ["user_id", "event_type"])
def test_create_needs_a_user_and_an_event(missing):
    values = payload()
    del values[missing]
    with pytest.raises(ValidationError):
        NotificationCreate(**values)


def test_create_rejects_an_unknown_event_type():
    with pytest.raises(ValidationError):
        NotificationCreate(**payload(event_type="NOPE"))


def test_create_rejects_a_user_id_that_is_not_an_id():
    with pytest.raises(ValidationError):
        NotificationCreate(**payload(user_id="not-an-id"))


def test_create_rejects_an_enquiry_id_that_is_not_an_id():
    with pytest.raises(ValidationError):
        NotificationCreate(**payload(enquiry_id="not-an-id"))


def test_create_rejects_an_unknown_field():
    with pytest.raises(ValidationError):
        NotificationCreate(**payload(colour="red"))


def test_read_shows_an_unread_notification():
    result = NotificationRead.model_validate(saved_notification())
    assert result.is_read is False
    assert result.read_at is None


def test_read_shows_a_read_notification():
    result = NotificationRead.model_validate(
        saved_notification(read_at=datetime.now(timezone.utc))
    )
    assert result.is_read is True


def test_read_includes_is_read_in_the_output():
    result = NotificationRead.model_validate(saved_notification())
    assert result.model_dump()["is_read"] is False


def test_read_keeps_the_references():
    enquiry_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    result = NotificationRead.model_validate(
        saved_notification(enquiry_id=enquiry_id, listing_id=listing_id)
    )
    assert result.enquiry_id == enquiry_id
    assert result.listing_id == listing_id


def test_unread_count_holds_a_number():
    assert UnreadCount(count=4).count == 4


def test_updated_count_holds_a_number():
    assert UpdatedCount(updated=2).updated == 2


def moment(day):
    return datetime(2026, 1, day, 10, 0, tzinfo=timezone.utc)


def test_create_saves_a_notification_that_can_be_found_again(session):
    user = make_business_owner(session)
    created = notification_repository.create(
        session,
        {"user_id": user.user_id, "event_type": NotificationEvent.PAYOUT_SENT},
    )
    found = notification_repository.get(session, created.notification_id)
    assert found.event_type == NotificationEvent.PAYOUT_SENT
    assert found.read_at is None


def test_get_returns_nothing_for_an_unknown_id(session):
    assert notification_repository.get(session, uuid.uuid4()) is None


def test_create_with_an_unknown_user_fails_and_the_session_still_works(session):
    with pytest.raises(IntegrityError):
        notification_repository.create(
            session,
            {"user_id": uuid.uuid4(), "event_type": NotificationEvent.PAYOUT_SENT},
        )
    user = make_business_owner(session)
    created = notification_repository.create(
        session,
        {"user_id": user.user_id, "event_type": NotificationEvent.PAYOUT_SENT},
    )
    assert created.notification_id is not None


def test_search_only_returns_the_notifications_of_that_user(session):
    first = make_business_owner(session)
    second = make_business_owner(session)
    mine = make_notification(session, first)
    make_notification(session, second)
    found = notification_repository.search(session, first.user_id)
    assert [n.notification_id for n in found] == [mine.notification_id]


def test_search_shows_the_newest_first(session):
    user = make_business_owner(session)
    make_notification(session, user, created_at=moment(1))
    newest = make_notification(session, user, created_at=moment(5))
    middle = make_notification(session, user, created_at=moment(3))
    found = notification_repository.search(session, user.user_id)
    assert found[0].notification_id == newest.notification_id
    assert found[1].notification_id == middle.notification_id


def test_search_can_show_only_the_unread(session):
    user = make_business_owner(session)
    unread = make_notification(session, user)
    make_notification(session, user, read_at=moment(2))
    found = notification_repository.search(session, user.user_id, unread_only=True)
    assert [n.notification_id for n in found] == [unread.notification_id]


def test_search_can_filter_by_event_type(session):
    user = make_business_owner(session)
    make_notification(session, user)
    failed = make_notification(
        session, user, event_type=NotificationEvent.PAYMENT_FAILED
    )
    found = notification_repository.search(
        session, user.user_id, event_type=NotificationEvent.PAYMENT_FAILED
    )
    assert [n.notification_id for n in found] == [failed.notification_id]


def test_search_pages_with_limit_and_offset(session):
    user = make_business_owner(session)
    for day in range(1, 4):
        make_notification(session, user, created_at=moment(day))
    assert len(notification_repository.search(session, user.user_id, limit=2)) == 2
    assert (
        len(notification_repository.search(session, user.user_id, limit=2, offset=2))
        == 1
    )


def test_count_unread_ignores_read_and_other_users(session):
    user = make_business_owner(session)
    other = make_business_owner(session)
    make_notification(session, user)
    make_notification(session, user)
    make_notification(session, user, read_at=moment(2))
    make_notification(session, other)
    assert notification_repository.count_unread(session, user.user_id) == 2


def test_count_unread_is_zero_when_there_are_none(session):
    user = make_business_owner(session)
    assert notification_repository.count_unread(session, user.user_id) == 0


def test_mark_read_sets_the_time(session):
    user = make_business_owner(session)
    notification = make_notification(session, user)
    result = notification_repository.mark_read(session, notification)
    assert result.read_at is not None


def test_mark_read_keeps_the_first_time(session):
    user = make_business_owner(session)
    notification = make_notification(session, user, read_at=moment(2))
    result = notification_repository.mark_read(session, notification)
    assert result.read_at == moment(2)


def test_mark_all_read_only_changes_that_users_unread(session):
    user = make_business_owner(session)
    other = make_business_owner(session)
    make_notification(session, user)
    make_notification(session, user)
    make_notification(session, user, read_at=moment(2))
    untouched = make_notification(session, other)
    updated = notification_repository.mark_all_read(session, user.user_id)
    assert updated == 2
    assert notification_repository.count_unread(session, user.user_id) == 0
    session.refresh(untouched)
    assert untouched.read_at is None


def test_delete_removes_the_notification(session):
    user = make_business_owner(session)
    notification = make_notification(session, user)
    notification_repository.delete(session, notification)
    assert notification_repository.get(session, notification.notification_id) is None


def build_notification(user_id, **changes):
    values = {
        "notification_id": uuid.uuid4(),
        "user_id": user_id,
        "event_type": NotificationEvent.ENQUIRY_RECEIVED,
        "enquiry_id": None,
        "listing_id": None,
        "read_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    values.update(changes)
    return Notification(**values)


class FakeRepository:
    def __init__(self, notifications=None):
        self.notifications = list(notifications or [])
        self.search_call = None
        self.created = None
        self.deleted = None
        self.read_all_for = None
        self.fail_on_create = False

    def get(self, db, notification_id):
        for notification in self.notifications:
            if notification.notification_id == notification_id:
                return notification
        return None

    def search(self, db, user_id, **filters):
        self.search_call = {"user_id": user_id, **filters}
        return [n for n in self.notifications if n.user_id == user_id]

    def count_unread(self, db, user_id):
        return len(
            [
                n
                for n in self.notifications
                if n.user_id == user_id and n.read_at is None
            ]
        )

    def create(self, db, data):
        if self.fail_on_create:
            raise IntegrityError("insert", {}, Exception("bad reference"))
        self.created = data
        return build_notification(**data)

    def mark_read(self, db, db_obj):
        if db_obj.read_at is None:
            db_obj.read_at = datetime.now(timezone.utc)
        return db_obj

    def mark_all_read(self, db, user_id):
        self.read_all_for = user_id
        return 3

    def delete(self, db, db_obj):
        self.deleted = db_obj


def install(monkeypatch, repository):
    monkeypatch.setattr(service_module, "notification_repository", repository)
    return repository


@pytest.fixture
def admin():
    return SimpleNamespace(user_id=uuid.uuid4(), role="ADMIN")


@pytest.fixture
def seller():
    return SimpleNamespace(user_id=uuid.uuid4(), role="BUSINESS_USER")


@pytest.fixture
def stranger():
    return SimpleNamespace(user_id=uuid.uuid4(), role="GUEST")


def test_listing_uses_the_current_user_and_the_filters(monkeypatch, seller):
    mine = build_notification(seller.user_id)
    other = build_notification(uuid.uuid4())
    repository = install(monkeypatch, FakeRepository([mine, other]))
    result = notification_service.list_notifications(
        None,
        seller,
        unread_only=True,
        event_type=NotificationEvent.PAYMENT_FAILED,
        limit=10,
        offset=5,
    )
    assert result == [mine]
    assert repository.search_call["user_id"] == seller.user_id
    assert repository.search_call["unread_only"] is True
    assert repository.search_call["event_type"] == NotificationEvent.PAYMENT_FAILED
    assert repository.search_call["limit"] == 10
    assert repository.search_call["offset"] == 5


def test_an_admin_can_list_their_own_notifications(monkeypatch, admin):
    mine = build_notification(admin.user_id)
    install(monkeypatch, FakeRepository([mine]))
    assert notification_service.list_notifications(None, admin) == [mine]


def test_an_unknown_role_cannot_list_notifications(monkeypatch, stranger):
    install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        notification_service.list_notifications(None, stranger)
    assert error.value.status_code == 403
    assert error.value.detail == "Access denied: a guest cannot view notifications."


def test_unread_count_only_counts_the_current_users_unread(monkeypatch, seller):
    notifications = [
        build_notification(seller.user_id),
        build_notification(seller.user_id),
        build_notification(seller.user_id, read_at=datetime.now(timezone.utc)),
        build_notification(uuid.uuid4()),
    ]
    install(monkeypatch, FakeRepository(notifications))
    assert notification_service.unread_count(None, seller) == 2


def test_unread_count_is_refused_for_an_unknown_role(monkeypatch, stranger):
    install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        notification_service.unread_count(None, stranger)
    assert error.value.status_code == 403


def test_a_user_can_get_their_own_notification(monkeypatch, seller):
    mine = build_notification(seller.user_id)
    install(monkeypatch, FakeRepository([mine]))
    result = notification_service.get_notification(None, mine.notification_id, seller)
    assert result is mine


def test_a_user_cannot_get_someone_elses_notification(monkeypatch, seller):
    theirs = build_notification(uuid.uuid4())
    install(monkeypatch, FakeRepository([theirs]))
    with pytest.raises(HTTPException) as error:
        notification_service.get_notification(None, theirs.notification_id, seller)
    assert error.value.status_code == 404
    assert error.value.detail == "Notification not found."


def test_getting_a_missing_notification_gives_404(monkeypatch, seller):
    install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        notification_service.get_notification(None, uuid.uuid4(), seller)
    assert error.value.status_code == 404


def test_an_admin_can_create_a_notification(monkeypatch, admin):
    repository = install(monkeypatch, FakeRepository())
    target = uuid.uuid4()
    data = NotificationCreate(
        user_id=target, event_type=NotificationEvent.APPROVAL_DECISION
    )
    result = notification_service.create_notification(None, data, admin)
    assert result.user_id == target
    assert repository.created["event_type"] == NotificationEvent.APPROVAL_DECISION
    assert repository.created["enquiry_id"] is None
    assert repository.created["listing_id"] is None


def test_a_business_user_cannot_create_a_notification(monkeypatch, seller):
    repository = install(monkeypatch, FakeRepository())
    data = NotificationCreate(
        user_id=uuid.uuid4(), event_type=NotificationEvent.APPROVAL_DECISION
    )
    with pytest.raises(HTTPException) as error:
        notification_service.create_notification(None, data, seller)
    assert error.value.status_code == 403
    assert "cannot create notifications" in error.value.detail
    assert repository.created is None


def test_creating_with_an_unknown_reference_gives_422(monkeypatch, admin):
    repository = install(monkeypatch, FakeRepository())
    repository.fail_on_create = True
    data = NotificationCreate(
        user_id=uuid.uuid4(), event_type=NotificationEvent.APPROVAL_DECISION
    )
    with pytest.raises(HTTPException) as error:
        notification_service.create_notification(None, data, admin)
    assert error.value.status_code == 422
    assert error.value.detail == "The user, enquiry or listing does not exist."


def test_notify_creates_a_notification_without_a_login(monkeypatch):
    repository = install(monkeypatch, FakeRepository())
    user_id = uuid.uuid4()
    enquiry_id = uuid.uuid4()
    result = notification_service.notify(
        None, user_id, NotificationEvent.PAYMENT_SUCCEEDED, enquiry_id=enquiry_id
    )
    assert result.user_id == user_id
    assert repository.created["enquiry_id"] == enquiry_id


def test_a_user_can_mark_their_own_notification_as_read(monkeypatch, seller):
    mine = build_notification(seller.user_id)
    install(monkeypatch, FakeRepository([mine]))
    result = notification_service.mark_read(None, mine.notification_id, seller)
    assert result.read_at is not None


def test_a_user_cannot_mark_someone_elses_notification_as_read(monkeypatch, seller):
    theirs = build_notification(uuid.uuid4())
    install(monkeypatch, FakeRepository([theirs]))
    with pytest.raises(HTTPException) as error:
        notification_service.mark_read(None, theirs.notification_id, seller)
    assert error.value.status_code == 404
    assert theirs.read_at is None


def test_an_unknown_role_cannot_mark_a_notification_as_read(monkeypatch, stranger):
    install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        notification_service.mark_read(None, uuid.uuid4(), stranger)
    assert error.value.status_code == 403
    assert "cannot update notifications" in error.value.detail


def test_mark_all_read_works_for_the_current_user_only(monkeypatch, seller):
    repository = install(monkeypatch, FakeRepository())
    assert notification_service.mark_all_read(None, seller) == 3
    assert repository.read_all_for == seller.user_id


def test_an_unknown_role_cannot_mark_all_as_read(monkeypatch, stranger):
    repository = install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        notification_service.mark_all_read(None, stranger)
    assert error.value.status_code == 403
    assert repository.read_all_for is None


def test_a_user_can_delete_their_own_notification(monkeypatch, seller):
    mine = build_notification(seller.user_id)
    repository = install(monkeypatch, FakeRepository([mine]))
    notification_service.delete_notification(None, mine.notification_id, seller)
    assert repository.deleted is mine


def test_a_user_cannot_delete_someone_elses_notification(monkeypatch, seller):
    theirs = build_notification(uuid.uuid4())
    repository = install(monkeypatch, FakeRepository([theirs]))
    with pytest.raises(HTTPException) as error:
        notification_service.delete_notification(None, theirs.notification_id, seller)
    assert error.value.status_code == 404
    assert repository.deleted is None


def test_an_unknown_role_cannot_delete_a_notification(monkeypatch, stranger):
    install(monkeypatch, FakeRepository())
    with pytest.raises(HTTPException) as error:
        notification_service.delete_notification(None, uuid.uuid4(), stranger)
    assert error.value.status_code == 403
    assert "cannot delete notifications" in error.value.detail


URL = "/notifications"


def headers_for(user):
    token = create_access_token(
        user.user_id, user.user_role, token_version=user.token_version
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_api(session):
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


def test_an_admin_sees_only_their_own_notifications_too(
    client, session, admin_api, owner
):
    make_notification(session, owner)
    mine = make_notification(session, admin_api)
    response = client.get(URL, headers=headers_for(admin_api))
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


def test_an_admin_cannot_read_someone_elses_notification(
    client, session, admin_api, owner
):
    theirs = make_notification(session, owner)
    response = client.get(
        f"{URL}/{theirs.notification_id}", headers=headers_for(admin_api)
    )
    assert response.status_code == 404


def test_reading_an_unknown_notification_gives_404(client, owner):
    response = client.get(f"{URL}/{uuid.uuid4()}", headers=headers_for(owner))
    assert response.status_code == 404


def test_reading_a_malformed_id_gives_422(client, owner):
    response = client.get(f"{URL}/not-an-id", headers=headers_for(owner))
    assert response.status_code == 422


def test_an_admin_can_create_a_notification_api(client, admin_api, owner):
    body = {"user_id": str(owner.user_id), "event_type": "APPROVAL_DECISION"}
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 200
    created = response.json()
    assert created["user_id"] == str(owner.user_id)
    assert created["event_type"] == "APPROVAL_DECISION"
    assert created["is_read"] is False
    assert created["notification_id"]


def test_a_created_notification_shows_up_for_the_user(client, admin_api, owner):
    body = {"user_id": str(owner.user_id), "event_type": "PAYOUT_SENT"}
    client.post(URL, json=body, headers=headers_for(admin_api))
    response = client.get(URL, headers=headers_for(owner))
    assert [item["event_type"] for item in response.json()] == ["PAYOUT_SENT"]


def test_a_notification_can_point_to_an_enquiry_and_a_listing(
    client, session, admin_api, owner
):
    enquiry = make_open_enquiry(session)
    body = {
        "user_id": str(owner.user_id),
        "event_type": "ENQUIRY_RECEIVED",
        "enquiry_id": str(enquiry.enquiry_id),
        "listing_id": str(enquiry.listing_id),
    }
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 200
    assert response.json()["enquiry_id"] == str(enquiry.enquiry_id)
    assert response.json()["listing_id"] == str(enquiry.listing_id)


def test_a_business_user_cannot_create_a_notification_api(client, owner):
    body = {"user_id": str(owner.user_id), "event_type": "APPROVAL_DECISION"}
    response = client.post(URL, json=body, headers=headers_for(owner))
    assert response.status_code == 403
    assert "cannot create notifications" in response.json()["detail"]


def test_creating_needs_a_login(client, owner):
    body = {"user_id": str(owner.user_id), "event_type": "APPROVAL_DECISION"}
    assert client.post(URL, json=body).status_code == 401


def test_creating_for_a_user_that_does_not_exist_gives_422(client, admin_api):
    body = {"user_id": str(uuid.uuid4()), "event_type": "APPROVAL_DECISION"}
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 422
    assert response.json()["detail"] == "The user, enquiry or listing does not exist."


def test_creating_with_an_unknown_enquiry_gives_422(client, admin_api, owner):
    body = {
        "user_id": str(owner.user_id),
        "event_type": "ENQUIRY_RECEIVED",
        "enquiry_id": str(uuid.uuid4()),
    }
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 422


def test_creating_without_a_user_gives_422(client, admin_api):
    response = client.post(
        URL, json={"event_type": "PAYOUT_SENT"}, headers=headers_for(admin_api)
    )
    assert response.status_code == 422


def test_creating_with_an_unknown_event_type_gives_422(client, admin_api, owner):
    body = {"user_id": str(owner.user_id), "event_type": "NOPE"}
    response = client.post(URL, json=body, headers=headers_for(admin_api))
    assert response.status_code == 422


def test_creating_with_an_unknown_field_gives_422(client, admin_api, owner):
    body = {
        "user_id": str(owner.user_id),
        "event_type": "PAYOUT_SENT",
        "colour": "red",
    }
    response = client.post(URL, json=body, headers=headers_for(admin_api))
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


def test_a_user_cannot_mark_someone_elses_notification_as_read_api(
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
    assert response.status_code == 200
    again = client.get(path, headers=headers_for(owner))
    assert again.status_code == 404


def test_a_user_cannot_delete_someone_elses_notification_api(
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
