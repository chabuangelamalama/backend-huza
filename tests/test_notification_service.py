import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

import services.notification as service_module
from models.notification import Notification, NotificationEvent
from schemas.notification import NotificationCreate
from services.notification import notification_service


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
