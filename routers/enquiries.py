import uuid
from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.dependencies import get_current_user
from database import get_db
from models.user import User
from repositories.enquiry import enquiry_repository
from schemas.enquiry import EnquiryCreate, EnquiryRead
from services.enquiry import enquiry_service

router = APIRouter(prefix="/api/v1/enquiries", tags=["Enquiries"])


@router.post("/", response_model=EnquiryRead, status_code=status.HTTP_201_CREATED)
def create_enquiry(
    payload: EnquiryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return enquiry_service.create_enquiry(db, payload)


@router.get("/", response_model=List[EnquiryRead])
def list_enquiries(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return enquiry_repository.get_all(db)


@router.get("/{enquiry_id}", response_model=EnquiryRead)
def get_enquiry(
    enquiry_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return enquiry_service.get_enquiry(db, enquiry_id)


@router.post("/{enquiry_id}/accept", response_model=EnquiryRead)
def accept_enquiry(
    enquiry_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return enquiry_service.accept_enquiry(db, enquiry_id)


@router.post("/{enquiry_id}/open", response_model=EnquiryRead)
def open_enquiry(
    enquiry_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return enquiry_service.open_enquiry(db, enquiry_id)


@router.post("/{enquiry_id}/decline", response_model=EnquiryRead)
def decline_enquiry(
    enquiry_id: uuid.UUID,
    reason: str = "DECLINED",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return enquiry_service.decline_enquiry(db, enquiry_id)


@router.post("/{enquiry_id}/complete", response_model=EnquiryRead)
def complete_enquiry(
    enquiry_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return enquiry_service.complete_enquiry(db, enquiry_id)


@router.post("/{enquiry_id}/cancel", response_model=EnquiryRead)
def cancel_enquiry(
    enquiry_id: uuid.UUID,
    reason: str = "OTHER",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return enquiry_service.cancel_enquiry(db, enquiry_id, reason)


@router.post("/{enquiry_id}/payments", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def start_payment(
    enquiry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
):
    return {"detail": "not implemented"}
