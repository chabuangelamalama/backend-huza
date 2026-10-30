from typing import Annotated

from fastapi import APIRouter, Depends, Query

from core.dependencies import get_current_user
from models import User
from schemas.locations import PlaceResult
from services import locations as location_service

router = APIRouter(prefix="/businesses", tags=["Businesses"])

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/places", response_model=list[PlaceResult])
def search_places(
    user: CurrentUser,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
):
    return location_service.search_places(q, limit)
