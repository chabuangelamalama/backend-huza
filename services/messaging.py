import uuid
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.enquiry import EnquiryStatus
from repositories.enquiry import enquiry_repository
from repositories.messaging import message_repository
from models.message import Message
from schemas.messaging import MessageCreate


class MessageService:
    @staticmethod
    def create_message_secured(
        db: Session, enquiry_id: uuid.UUID, sender_business_id: uuid.UUID, payload: MessageCreate
    ) -> Message:
        """Appends a secure communication log inside an active transactional dialogue workspace flow."""
        # 1. Verify existence of the overarching pipeline entity context
        enquiry = enquiry_repository.get(db, enquiry_id)
        if not enquiry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target transaction pipeline context not found."
            )

        # 2. Enforce structural multi-partner identity access boundary locks
        if sender_business_id not in [enquiry.buyer_business_id, enquiry.seller_business_id]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to transmit data across this isolated transaction boundary channel."
            )

        # 3. Prevent commentary on permanently closed contract operations
        terminal_states = {EnquiryStatus.CANCELLED, EnquiryStatus.UNSUCCESSFUL, EnquiryStatus.COMPLETED}
        if enquiry.status in terminal_states:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot append message logs to a closed or terminated transaction sequence."
            )

        # 4. Construct payload data dictionary map for data-access execution layers
        data = {
            "enquiry_id": enquiry_id,
            "sender_business_id": sender_business_id,
            "content": payload.content,
        }
        return message_repository.create(db, data)

    @staticmethod
    def list_messages_secured(
        db: Session, enquiry_id: uuid.UUID, user_business_id: uuid.UUID
    ) -> Sequence[Message]:
        """Lists a clean historical timeline sequence log of historical messaging elements."""
        enquiry = enquiry_repository.get(db, enquiry_id)
        if not enquiry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target transaction pipeline context not found."
            )

        if user_business_id not in [enquiry.buyer_business_id, enquiry.seller_business_id]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this connection stream dialogue ledger."
            )

        return message_repository.get_by_enquiry(db, enquiry_id)


message_service = MessageService()
