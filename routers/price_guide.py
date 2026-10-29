import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from core.security import CurrentUser, get_current_user
from schemas.price_guide import (
    PriceCheck,
    PriceGuideCreate,
    PriceGuideFilter,
    PriceGuideRead,
    PriceGuideUpdate,
    PriceLookup,
)
from services.price_guide import price_guide_service

router = APIRouter(prefix="/price-guides", tags=["price guides"])


@router.get("", response_model=list[PriceGuideRead])
def list_price_guides(
    filters: Annotated[PriceGuideFilter, Query()],
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    guides = price_guide_service.list_price_guides(
        db, current_user, **filters.model_dump()
    )
    return [price_guide_service.present(guide, current_user) for guide in guides]


@router.get("/lookup", response_model=PriceCheck)
def look_up_price_guide(
    lookup: Annotated[PriceLookup, Query()],
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return price_guide_service.check_price(db, current_user, **lookup.model_dump())


@router.get("/{guide_id}", response_model=PriceGuideRead)
def get_price_guide(
    guide_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    guide = price_guide_service.get_price_guide(db, guide_id, current_user)
    return price_guide_service.present(guide, current_user)


@router.post("", response_model=PriceGuideRead)
def create_price_guide(
    data: PriceGuideCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    guide = price_guide_service.create_price_guide(db, data, current_user)
    return price_guide_service.present(guide, current_user)


@router.patch("/{guide_id}", response_model=PriceGuideRead)
def update_price_guide(
    guide_id: uuid.UUID,
    data: PriceGuideUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    guide = price_guide_service.update_price_guide(db, guide_id, data, current_user)
    return price_guide_service.present(guide, current_user)


@router.delete("/{guide_id}")
def delete_price_guide(
    guide_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    price_guide_service.delete_price_guide(db, guide_id, current_user)
