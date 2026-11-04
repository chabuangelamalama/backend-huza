import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from core.security import CurrentUser, get_current_user
from database import get_db
from schemas.enquiry import EnquiryCreate, EnquiryFilter, EnquiryRead
from services.enquiry import enquiry_service

router = APIRouter(prefix="/enquiries", tags=["enquiries"])


@router.post("", response_model=EnquiryRead, status_code=status.HTTP_201_CREATED)
def create_enquiry(
    payload: EnquiryCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return enquiry_service.create_enquiry(db, payload, current_user)


@router.get("", response_model=list[EnquiryRead])
def list_enquiries(
    filters: Annotated[EnquiryFilter, Query()],
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return enquiry_service.list_enquiries(
        db,
        current_user,
        **filters.model_dump(),
    )


@router.get("/{enquiry_id}", response_model=EnquiryRead)
def get_enquiry(
    enquiry_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return enquiry_service.get_enquiry(db, enquiry_id, current_user)


@router.post("/{enquiry_id}/accept", response_model=EnquiryRead)
def accept_enquiry(
    enquiry_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Seller accepts the enquiry (ENQUIRY -> AGREED) so the buyer can pay."""
    return enquiry_service.accept_enquiry(db, enquiry_id, current_user)
