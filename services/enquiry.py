import uuid
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.enquiry import EnquiryStatus
from repositories.enquiry import enquiry_repository
from schemas.enquiry import EnquiryCreate


class EnquiryService:
    def _get_enquiry_or_404(self, db: Session, enquiry_id: uuid.UUID):
        enquiry = enquiry_repository.get(db, enquiry_id)
        if not enquiry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="not found"
            )
        return enquiry

    def create_enquiry(self, db: Session, payload: EnquiryCreate):
        total_amount = payload.quantity * payload.unit_price
        data = {
            "listing_id": payload.listing_id,
            "buyer_business_id": payload.buyer_business_id,
            "seller_business_id": payload.seller_business_id,
            "quantity": payload.quantity,
            "unit": payload.unit,
            "unit_price": payload.unit_price,
            "total_amount": total_amount,
            "status": EnquiryStatus.ENQUIRY,
        }
        return enquiry_repository.create(db, data)

    def get_enquiry(self, db: Session, enquiry_id: uuid.UUID):
        return self._get_enquiry_or_404(db, enquiry_id)

    def open_enquiry(self, db: Session, enquiry_id: uuid.UUID):
        enquiry = self._get_enquiry_or_404(db, enquiry_id)
        return enquiry_repository.update(db, enquiry, {"status": EnquiryStatus.ENQUIRY})


enquiry_service = EnquiryService()
