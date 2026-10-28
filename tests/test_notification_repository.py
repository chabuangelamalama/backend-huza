import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from models.notification import NotificationEvent
from repositories.notification import notification_repository
from tests.notification_helpers import (
    make_business_owner,
    make_notification,
)


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
