from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class MessageCreate(BaseModel):
    content: str = Field(
        ..., min_length=1, max_length=5000, description="The message text payload."
    )


class MessageRead(BaseModel):
    message_id: UUID
    enquiry_id: UUID
    sender_business_id: UUID
    content: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
