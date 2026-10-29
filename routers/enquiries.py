import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.enquiry import EnquiryStatus, FailureReason
from repositories.enquiry import enquiry_repository
from schemas.enquiry import EnquiryCreate, EnquiryRead

router = APIRouter(prefix="/api/v1/enquiries", tags=["Enquiries"])


@router.post("/", response_model=EnquiryRead, status_code=status.HTTP_201_CREATED)
def create_enquiry(payload: EnquiryCreate, db: Session = Depends(get_db)):
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


@router.get("/", response_model=List[EnquiryRead])
def list_enquiries(db: Session = Depends(get_db)):
    return enquiry_repository.get_all(db)


@router.get("/{enquiry_id}", response_model=EnquiryRead)
def get_enquiry(enquiry_id: uuid.UUID, db: Session = Depends(get_db)):
    enquiry = enquiry_repository.get(db, enquiry_id)
    if not enquiry:
        raise HTTPException(status_code=404, detail="not found")
    return enquiry


@router.post("/{enquiry_id}/accept", response_model=EnquiryRead)
def accept_enquiry(enquiry_id: uuid.UUID, db: Session = Depends(get_db)):
    enquiry = enquiry_repository.get(db, enquiry_id)
    if not enquiry:
        raise HTTPException(status_code=404, detail="not found")
    return enquiry_repository.update(
        db,
        enquiry,
        {"status": EnquiryStatus.AGREED, "accepted_at": datetime.now(timezone.utc)},
    )


@router.post("/{enquiry_id}/open", response_model=EnquiryRead)
def open_enquiry(enquiry_id: uuid.UUID, db: Session = Depends(get_db)):
    enquiry = enquiry_repository.get(db, enquiry_id)
    if not enquiry:
        raise HTTPException(status_code=404, detail="not found")
    return enquiry_repository.update(db, enquiry, {"status": EnquiryStatus.ENQUIRY})


@router.post("/{enquiry_id}/decline", response_model=EnquiryRead)
def decline_enquiry(
    enquiry_id: uuid.UUID, reason: str = "DECLINED", db: Session = Depends(get_db)
):
    enquiry = enquiry_repository.get(db, enquiry_id)
    if not enquiry:
        raise HTTPException(status_code=404, detail="not found")
    return enquiry_repository.update(
        db,
        enquiry,
        {
            "status": EnquiryStatus.UNSUCCESSFUL,
            "failure_reason": FailureReason.DECLINED,
        },
    )


@router.post("/{enquiry_id}/complete", response_model=EnquiryRead)
def complete_enquiry(enquiry_id: uuid.UUID, db: Session = Depends(get_db)):
    enquiry = enquiry_repository.get(db, enquiry_id)
    if not enquiry:
        raise HTTPException(status_code=404, detail="not found")
    return enquiry_repository.update(
        db,
        enquiry,
        {"status": EnquiryStatus.COMPLETED, "closed_at": datetime.now(timezone.utc)},
    )


@router.post("/{enquiry_id}/cancel", response_model=EnquiryRead)
def cancel_enquiry(
    enquiry_id: uuid.UUID, reason: str = "OTHER", db: Session = Depends(get_db)
):
    enquiry = enquiry_repository.get(db, enquiry_id)
    if not enquiry:
        raise HTTPException(status_code=404, detail="not found")
    return enquiry_repository.update(
        db,
        enquiry,
        {
            "status": EnquiryStatus.CANCELLED,
            "failure_reason": FailureReason(reason),
            "closed_at": datetime.now(timezone.utc),
        },
    )


@router.post("/{enquiry_id}/payments", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def start_payment(enquiry_id: uuid.UUID):
    return {"detail": "not implemented"}
