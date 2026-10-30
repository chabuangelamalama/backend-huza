from fastapi import APIRouter, Depends

from core.dependencies import get_current_user, get_registration_service
from models.user import User
from schemas.registration import BusinessOut, BusinessUpdate
from services.registration_service import RegistrationService

router = APIRouter(prefix="/business", tags=["business"])


@router.get("/me", response_model=BusinessOut)
def my_business(
    user: User = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
):
    """The signed-in user's business, including its approval status."""
    return service.get_business(user)


@router.patch("/me", response_model=BusinessOut)
def update_my_business(
    body: BusinessUpdate,
    user: User = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
):
    """Edit business details while the business is pending or rejected."""
    return service.update_business(user, body)
