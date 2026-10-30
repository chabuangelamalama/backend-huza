from fastapi import APIRouter, Depends, Query

from core.dependencies import get_current_user
from models import User
from schemas.locations import PlaceResult
from services import locations as location_service

router = APIRouter(prefix="/businesses", tags=["Businesses"])


@router.get("/places", response_model=list[PlaceResult])
def search_places(
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(5, ge=1, le=10),
    user: User = Depends(get_current_user),
):
    return location_service.search_places(q, limit)
