from typing import Annotated

from fastapi import APIRouter, Depends, Query

from core.dependencies import get_current_user
from models import User
from schemas.locations import PlaceResult, PlaceSearch
from services import locations as location_service

router = APIRouter(prefix="/businesses", tags=["Businesses"])


@router.get("/places", response_model=list[PlaceResult])
def search_places(
    search: Annotated[PlaceSearch, Query()],
    user: User = Depends(get_current_user),
):
    return location_service.search_places(search.q, search.limit)
