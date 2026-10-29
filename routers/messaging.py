import uuid
from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from database import get_db
from schemas.messaging import MessageCreate, MessageRead
from services.messaging import message_service

router = APIRouter(prefix="/enquiries/{enquiry_id}/messages", tags=["Messages"])


@router.post(
    "/",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    enquiry_id: uuid.UUID,
    payload: MessageCreate,
    sender_business_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Create a message in an enquiry."""

    return message_service.create_message_secured(
        db=db,
        enquiry_id=enquiry_id,
        sender_business_id=sender_business_id,
        payload=payload,
    )


@router.get("/", response_model=List[MessageRead])
def list_messages(
    enquiry_id: uuid.UUID,
    user_business_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List messages for an enquiry."""
    return message_service.list_messages_secured(
        db=db,
        enquiry_id=enquiry_id,
        user_business_id=user_business_id,
    )
