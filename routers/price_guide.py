import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import CurrentUser, get_current_user
from models.listing import Stream, Unit
from schemas.price_guide import (
    PriceCheck,
    PriceGuideCreate,
    PriceGuideRead,
    PriceGuideUpdate,
)
from services.price_guide import price_guide_service

router = APIRouter(prefix="/price-guides", tags=["price guides"])


@router.get("", response_model=list[PriceGuideRead])
def list_price_guides(
    stream: Stream | None = None,
    material: Annotated[str | None, Query(max_length=150)] = None,
    grade: Annotated[str | None, Query(max_length=100)] = None,
    unit: Unit | None = None,
    district: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return price_guide_service.list_price_guides(
        db,
        current_user,
        stream=stream,
        material=material,
        grade=grade,
        unit=unit,
        district=district,
        limit=limit,
        offset=offset,
    )


@router.get("/lookup", response_model=PriceCheck)
def look_up_price_guide(
    stream: Stream,
    material: Annotated[str, Query(min_length=1, max_length=150)],
    unit: Unit,
    grade: Annotated[str | None, Query(max_length=100)] = None,
    price: Annotated[Decimal | None, Query(gt=0)] = None,
    district: Annotated[str | None, Query(max_length=100)] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return price_guide_service.check_price(
        db,
        current_user,
        stream=stream,
        material=material,
        unit=unit,
        grade=grade,
        price=price,
        district=district,
    )


@router.get("/{guide_id}", response_model=PriceGuideRead)
def get_price_guide(
    guide_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return price_guide_service.get_price_guide(db, guide_id, current_user)


@router.post("", response_model=PriceGuideRead, status_code=status.HTTP_201_CREATED)
def create_price_guide(
    data: PriceGuideCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return price_guide_service.create_price_guide(db, data, current_user)


@router.patch("/{guide_id}", response_model=PriceGuideRead)
def update_price_guide(
    guide_id: uuid.UUID,
    data: PriceGuideUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return price_guide_service.update_price_guide(db, guide_id, data, current_user)


@router.delete(
    "/{guide_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_price_guide(
    guide_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    price_guide_service.delete_price_guide(db, guide_id, current_user)