import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from models.enquiry import EnquiryStatus, FailureReason
from models.listing import Unit


class EnquiryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing_id: uuid.UUID
    buyer_business_id: uuid.UUID
    seller_business_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit: Unit
    unit_price: Decimal = Field(gt=0, max_digits=19, decimal_places=4)


class EnquiryFilter(BaseModel):
    status: EnquiryStatus | None = None
    listing_id: uuid.UUID | None = None
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)


class EnquiryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enquiry_id: uuid.UUID
    listing_id: uuid.UUID
    buyer_business_id: uuid.UUID
    seller_business_id: uuid.UUID
    status: EnquiryStatus
    quantity: Decimal
    unit: Unit
    unit_price: Decimal
    total_amount: Decimal
    failure_reason: FailureReason | None
    first_response_at: datetime | None
    accepted_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
