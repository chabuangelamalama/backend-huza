import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from models.notification import NotificationEvent


class NotificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    event_type: NotificationEvent
    enquiry_id: uuid.UUID | None = None
    listing_id: uuid.UUID | None = None


class NotificationFilter(BaseModel):
    unread_only: bool = False
    event_type: NotificationEvent | None = None
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: uuid.UUID
    user_id: uuid.UUID
    event_type: NotificationEvent
    enquiry_id: uuid.UUID | None
    listing_id: uuid.UUID | None
    read_at: datetime | None
    created_at: datetime

    @computed_field
    @property
    def is_read(self) -> bool:
        return self.read_at is not None


class UnreadCount(BaseModel):
    count: int


class UpdatedCount(BaseModel):
    updated: int
