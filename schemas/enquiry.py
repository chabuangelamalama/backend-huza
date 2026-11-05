import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from models.enquiry import EnquiryStatus, FailureReason
from models.listing import Unit

# Phone and email are shared only once the seller has accepted, so the two
# sides cannot arrange the deal off the platform before agreeing on it here.
CONTACT_VISIBLE_STATUSES = {
    EnquiryStatus.AGREED,
    EnquiryStatus.PAID,
    EnquiryStatus.COMPLETED,
}


class EnquiryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing_id: uuid.UUID
    buyer_business_id: uuid.UUID
    seller_business_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit: Unit
    unit_price: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    message: str | None = Field(None, max_length=1000)

    @field_validator("message")
    @classmethod
    def _blank_message_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class EnquiryClose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[EnquiryStatus.CANCELLED, EnquiryStatus.UNSUCCESSFUL]
    failure_reason: FailureReason


class EnquiryFilter(BaseModel):
    status: EnquiryStatus | None = None
    listing_id: uuid.UUID | None = None
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)


class EnquiryParty(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    business_id: uuid.UUID
    name: str = Field(validation_alias=AliasChoices("public_name", "name"))
    phone: str | None = Field(
        None, validation_alias=AliasChoices("contact_phone", "phone")
    )
    email: str | None = Field(
        None, validation_alias=AliasChoices("contact_email", "email")
    )


class EnquiryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enquiry_id: uuid.UUID
    listing_id: uuid.UUID
    buyer_business_id: uuid.UUID
    seller_business_id: uuid.UUID
    buyer: EnquiryParty | None = None
    seller: EnquiryParty | None = None
    status: EnquiryStatus
    quantity: Decimal
    unit: Unit
    unit_price: Decimal
    total_amount: Decimal
    message: str | None = None
    failure_reason: FailureReason | None
    first_response_at: datetime | None
    accepted_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _hide_contacts_until_agreed(self):
        if self.status not in CONTACT_VISIBLE_STATUSES:
            for party in (self.buyer, self.seller):
                if party is not None:
                    party.phone = None
                    party.email = None
        return self
