import uuid

from fastapi import APIRouter, Depends, Query

from core.dependencies import get_user_service, require_admin
from models.user import UserRole
from schemas.auth import UserOut, UserPage
from services.user_service import UserService


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/users", response_model=UserPage)
def list_users(
    role: UserRole | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: UserService = Depends(get_user_service),
):
    items, total = service.list_users(role=role, limit=limit, offset=offset)
    return UserPage(
        items=[UserOut.model_validate(u) for u in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/users/{user_id}/unlock", response_model=UserOut)
def unlock_user(
    user_id: uuid.UUID,
    service: UserService = Depends(get_user_service),
):
    """Clear a lockout caused by too many failed sign-ins."""
    return UserOut.model_validate(service.unlock(user_id))
