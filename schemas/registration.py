import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from models.business import ApprovalStatus, BusinessRole, BusinessType, SupplierKind
from models.listing import Stream
from models.location import OsmType
from schemas.auth import _check_password_rules

TRIMMED = ConfigDict(str_strip_whitespace=True)


class LocationIn(BaseModel):
    """A place picked in the app. Send osm_type and osm_id when the place comes
    from OpenStreetMap; leave both out for a manually chosen place."""

    model_config = TRIMMED

    name: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=500)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    sub_county: str = Field(min_length=1, max_length=100)
    county: str = Field(min_length=1, max_length=100)
    osm_type: OsmType | None = None
    osm_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _osm_fields_go_together(self) -> "LocationIn":
        if (self.osm_type is None) != (self.osm_id is None):
            raise ValueError("osm_type and osm_id must be sent together.")
        return self


class BusinessIn(BaseModel):
    model_config = TRIMMED

    business_legal_name: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    registration_number: str | None = Field(default=None, max_length=100)
    business_type: BusinessType = BusinessType.BUSINESS
    supplier_kind: SupplierKind | None = None
    streams: list[Stream] = Field(min_length=1)
    contact_phone: str | None = Field(default=None, max_length=30)


class RegisterRequest(BaseModel):
    model_config = TRIMMED

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    password: str = Field(max_length=128)
    business_role: BusinessRole
    business: BusinessIn
    location: LocationIn

    @model_validator(mode="after")
    def _rules(self) -> "RegisterRequest":
        _check_password_rules(self.password)
        if (
            self.business.business_type == BusinessType.CONSUMER
            and self.business_role != BusinessRole.BUYER
        ):
            raise ValueError("Only buyers can be consumers.")
        if (
            self.business.supplier_kind is not None
            and self.business_role != BusinessRole.SUPPLIER
        ):
            raise ValueError("supplier_kind is only for suppliers.")
        return self


class BusinessUpdate(BaseModel):
    """Only the fields that are sent are changed."""

    model_config = TRIMMED

    business_legal_name: str | None = Field(default=None, min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    registration_number: str | None = Field(default=None, max_length=100)
    business_type: BusinessType | None = None
    supplier_kind: SupplierKind | None = None
    streams: list[Stream] | None = Field(default=None, min_length=1)
    contact_phone: str | None = Field(default=None, max_length=30)
    location: LocationIn | None = None


class CodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: uuid.UUID
    name: str
    display_name: str
    sub_county: str
    county: str
    latitude: float
    longitude: float


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    business_id: uuid.UUID
    business_legal_name: str
    display_name: str | None
    registration_number: str | None
    business_role: BusinessRole
    business_type: BusinessType
    supplier_kind: SupplierKind | None
    streams: list[str]
    contact_phone: str | None
    contact_email: str
    approval_status: ApprovalStatus
    rejection_reason: str | None
    location: LocationOut
