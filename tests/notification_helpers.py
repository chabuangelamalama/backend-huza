import uuid

from models.notification import NotificationEvent
from models.user import UserRole
from tests.test_models import (
    make_business,
    make_listing,
    make_location,
    make_notification,
    make_open_enquiry,
    make_user,
)

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
