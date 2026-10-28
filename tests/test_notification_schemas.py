import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.notification import Notification, NotificationEvent
from schemas.notification import (
    NotificationCreate,
    NotificationRead,
    UnreadCount,
    UpdatedCount,
)


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
