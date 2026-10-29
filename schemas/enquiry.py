from pydantic import BaseModel, ConfigDict
from decimal import Decimal
import uuid


class EnquiryCreate(BaseModel):
    listing_id: uuid.UUID
    buyer_business_id: uuid.UUID
    seller_business_id: uuid.UUID
    quantity: Decimal
    unit: str
    unit_price: Decimal


class EnquiryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enquiry_id: uuid.UUID
    listing_id: uuid.UUID
    buyer_business_id: uuid.UUID
    seller_business_id: uuid.UUID
    status: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    total_amount: Decimal
