import itertools
from decimal import Decimal

from core.security import create_access_token
from models import Business, Location, User
from models.business import ApprovalStatus, BusinessRole, BusinessType
from models.location import OsmType
from models.user import UserRole

_counter = itertools.count(1)


def location_payload(**changes):
    payload = {
        "osm_type": "node",
        "osm_id": 1000 + next(_counter),
        "name": "Westlands",
        "display_name": "Westlands, Nairobi, Nairobi County, Kenya",
        "latitude": -1.2675,
        "longitude": 36.8108,
        "sub_county": "Westlands",
        "county": "Nairobi",
    }
    payload.update(changes)
    return payload


def make_location(session, **changes):
    values = {
        "osm_type": OsmType.NODE,
        "osm_id": 5000 + next(_counter),
        "name": "Westlands",
        "display_name": "Westlands, Nairobi, Nairobi County, Kenya",
        "latitude": Decimal("-1.267500"),
        "longitude": Decimal("36.810800"),
        "sub_county": "Westlands",
        "county": "Nairobi",
    }
    values.update(changes)
    location = Location(**values)
    session.add(location)
    session.flush()
    return location


def make_business(session, location=None, **changes):
    location = location or make_location(session)
    values = {
        "business_legal_name": "Nairobi Timber Works Ltd",
        "business_role": BusinessRole.SUPPLIER,
        "business_type": BusinessType.BUSINESS,
        "location_id": location.location_id,
        "streams": ["SAWDUST"],
        "contact_email": "info@nairobitimber.co.ke",
        "contact_phone": "+254712345678",
        "approval_status": ApprovalStatus.PENDING,
    }
    values.update(changes)
    business = Business(**values)
    session.add(business)
    session.flush()
    return business


def make_user(session, business=None, **changes):
    number = next(_counter)
    values = {
        "business_id": business.business_id if business else None,
        "first_name": "Jean",
        "last_name": "Habimana",
        "email": f"user{number}@example.co.ke",
        "password_hash": "x",
        "user_role": UserRole.BUSINESS_USER if business else UserRole.ADMIN,
    }
    values.update(changes)
    user = User(**values)
    session.add(user)
    session.flush()
    return user


def auth(user):
    token = create_access_token(user.user_id, user.user_role, user.token_version)
    return {"Authorization": f"Bearer {token.token}"}
