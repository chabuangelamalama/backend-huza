import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from core.config import Settings
from core.exceptions import (
    BusinessNotEditable,
    EmailTaken,
    InvalidBusinessDetails,
    InvalidVerificationCode,
    NotFound,
)
from core.security import hash_password, verify_and_update
from models.business import ApprovalStatus, Business, BusinessRole, BusinessType
from models.location import Location, OsmType
from models.user import User, UserRole
from repositories.user_repository import UserRepository
from schemas.registration import BusinessUpdate, LocationIn, RegisterRequest
from services.auth_service import normalize_email
from services.email_service import OutgoingEmail, build_verification_code_email

SIX_DP = Decimal("0.000001")
EDITABLE_STATUSES = (ApprovalStatus.PENDING, ApprovalStatus.REJECTED)

REQUIRED_FIELDS = {"business_legal_name", "business_type", "streams"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def manual_osm_id(latitude: Decimal, longitude: Decimal) -> int:
    """Id for a place that did not come from OpenStreetMap. It is negative, so it
    can never clash with a real OSM id, and the same spot always gets the same id."""
    digest = hashlib.sha256(f"{latitude}:{longitude}".encode()).digest()
    return -(int.from_bytes(digest[:7], "big") + 1)


def _unique(streams) -> list[str]:
    return list(dict.fromkeys(str(s) for s in streams))


class RegistrationService:
    def __init__(self, users: UserRepository, settings: Settings) -> None:
        self.users = users
        self.settings = settings

    def register(self, data: RegisterRequest) -> tuple[User, OutgoingEmail | None]:
        """Creates the location, the PENDING business and the user in one go."""
        email = normalize_email(data.email)
        if self.users.get_by_email(email) is not None:
            raise EmailTaken()

        location = self._location_for(data.location)
        details = data.business
        auto_approve = self.settings.auto_approve_businesses
        auto_verify = self.settings.auto_verify_email
        business = Business(
            business_legal_name=details.business_legal_name,
            display_name=details.display_name,
            business_role=data.business_role,
            business_type=details.business_type,
            supplier_kind=details.supplier_kind,
            location_id=location.location_id,
            streams=_unique(details.streams),
            contact_phone=details.contact_phone or data.phone,
            contact_email=email,
            registration_number=details.registration_number,
            approval_status=(
                ApprovalStatus.APPROVED if auto_approve else ApprovalStatus.PENDING
            ),
            approved_at=_now() if auto_approve else None,
        )
        self.users.add(business)
        self.users.flush()

        code = self._new_code()
        user = User(
            first_name=data.first_name,
            last_name=data.last_name,
            email=email,
            phone=data.phone,
            password_hash=hash_password(data.password),
            user_role=UserRole.BUSINESS_USER,
            business_id=business.business_id,
        )
        self._store_code(user, code)
        if auto_verify:
            user.email_verified_at = _now()
            user.verify_code_hash = None
            user.verify_code_expires_at = None
        self.users.add(user)
        try:
            self.users.commit()
        except IntegrityError:
            self.users.rollback()
            raise EmailTaken() from None
        if auto_verify:
            return user, None
        return user, build_verification_code_email(user, code, self.settings)

    def send_verification(self, user: User) -> OutgoingEmail | None:
        """New code for the signed-in user. None when already verified."""
        if user.email_verified_at is not None:
            return None
        code = self._new_code()
        self._store_code(user, code)
        self.users.commit()
        return build_verification_code_email(user, code, self.settings)

    def verify_email(self, user: User, code: str) -> None:
        if user.email_verified_at is not None:
            return
        if not user.verify_code_hash or not user.verify_code_expires_at:
            raise InvalidVerificationCode()

        expires_at = _aware(user.verify_code_expires_at)
        if expires_at is None or _now() > expires_at:
            user.verify_code_hash = None
            user.verify_code_expires_at = None
            self.users.commit()
            raise InvalidVerificationCode()

        valid, _ = verify_and_update(code.strip(), user.verify_code_hash)
        if not valid:
            raise InvalidVerificationCode()

        user.email_verified_at = _now()
        user.verify_code_hash = None
        user.verify_code_expires_at = None
        self.users.commit()

    def get_business(self, user: User) -> Business:
        if user.business is None:
            raise NotFound("This account has no business.")
        return user.business

    def update_business(self, user: User, data: BusinessUpdate) -> Business:
        """Pending and rejected businesses can be edited. Saving a rejected one
        sends it back for review."""
        business = self.get_business(user)
        if business.approval_status not in EDITABLE_STATUSES:
            raise BusinessNotEditable()

        changes = data.model_dump(exclude_unset=True, exclude={"location"})
        for key, value in changes.items():
            if value is None and key in REQUIRED_FIELDS:
                continue
            if key == "streams":
                value = _unique(value)
            setattr(business, key, value)

        if data.location is not None:
            business.location = self._location_for(data.location)

        if (
            business.business_type == BusinessType.CONSUMER
            and business.business_role != BusinessRole.BUYER
        ):
            self.users.rollback()
            raise InvalidBusinessDetails("Only buyers can be consumers.")
        if (
            business.supplier_kind is not None
            and business.business_role != BusinessRole.SUPPLIER
        ):
            self.users.rollback()
            raise InvalidBusinessDetails("supplier_kind is only for suppliers.")

        if business.approval_status == ApprovalStatus.REJECTED:
            business.approval_status = ApprovalStatus.PENDING
            business.rejection_reason = None
        self.users.commit()
        return business

    def _location_for(self, place: LocationIn) -> Location:
        latitude = Decimal(str(place.latitude)).quantize(SIX_DP)
        longitude = Decimal(str(place.longitude)).quantize(SIX_DP)
        if place.osm_type is not None and place.osm_id is not None:
            osm_type, osm_id = place.osm_type, place.osm_id
        else:
            osm_type, osm_id = OsmType.NODE, manual_osm_id(latitude, longitude)

        existing = self.users.find_location(osm_type, osm_id)
        if existing is not None:
            return existing

        location = Location(
            osm_type=osm_type,
            osm_id=osm_id,
            name=place.name,
            display_name=place.display_name or place.name,
            latitude=latitude,
            longitude=longitude,
            sub_county=place.sub_county,
            county=place.county,
        )
        self.users.add(location)
        self.users.flush()
        return location

    @staticmethod
    def _new_code() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    def _store_code(self, user: User, code: str) -> None:
        user.verify_code_hash = hash_password(code)
        user.verify_code_expires_at = _now() + timedelta(
            minutes=self.settings.verify_code_minutes
        )
