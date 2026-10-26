import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import CurrentUser, get_current_user, require_admin
from models.enums import Stream, Unit
from repositories.price_guides import PriceGuideRepository
from schemas.price_guides import (
    PriceCheck,
    PriceGuideCreate,
    PriceGuideRead,
    PriceGuideUpdate,
)
from services.price_guides import (
    InvalidPriceRange,
    PriceGuideNotFound,
    PriceGuideService,
    UnknownUser,
)

router = APIRouter(prefix="/price-guides", tags=["price guides"])


def get_service(db: Session = Depends(get_db)) -> PriceGuideService:
    return PriceGuideService(PriceGuideRepository(db))


Service = Annotated[PriceGuideService, Depends(get_service)]
LoggedIn = Annotated[CurrentUser, Depends(get_current_user)]
Admin = Annotated[CurrentUser, Depends(require_admin)]


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Price guide not found")


def bad_range() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, "Max price cannot be below min price"
    )


@router.get("", response_model=list[PriceGuideRead])
def list_price_guides(
    service: Service,
    _user: LoggedIn,
    stream: Stream | None = None,
    material: Annotated[str | None, Query(max_length=150)] = None,
    unit: Unit | None = None,
    district: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return service.list(
        stream=stream,
        material=material,
        unit=unit,
        district=district,
        limit=limit,
        offset=offset,
    )


@router.get("/lookup", response_model=PriceCheck)
def look_up_price_guide(
    service: Service,
    _user: LoggedIn,
    stream: Stream,
    material: Annotated[str, Query(min_length=1, max_length=150)],
    unit: Unit,
    price: Annotated[Decimal | None, Query(gt=0)] = None,
    district: Annotated[str | None, Query(max_length=100)] = None,
):
    guide, position = service.check(
        stream=stream, material=material, unit=unit, price=price, district=district
    )
    return PriceCheck(
        guide=PriceGuideRead.model_validate(guide) if guide else None,
        position=position,
    )


@router.get("/{guide_id}", response_model=PriceGuideRead)
def get_price_guide(guide_id: uuid.UUID, service: Service, _user: LoggedIn):
    try:
        return service.get(guide_id)
    except PriceGuideNotFound:
        raise not_found() from None


@router.post("", response_model=PriceGuideRead, status_code=status.HTTP_201_CREATED)
def create_price_guide(data: PriceGuideCreate, service: Service, admin: Admin):
    try:
        return service.create(data, admin.user_id)
    except UnknownUser:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your login is not valid"
        ) from None


@router.patch("/{guide_id}", response_model=PriceGuideRead)
def update_price_guide(
    guide_id: uuid.UUID, data: PriceGuideUpdate, service: Service, _admin: Admin
):
    try:
        return service.update(guide_id, data)
    except PriceGuideNotFound:
        raise not_found() from None
    except InvalidPriceRange:
        raise bad_range() from None


@router.delete(
    "/{guide_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_price_guide(guide_id: uuid.UUID, service: Service, _admin: Admin):
    try:
        service.delete(guide_id)
    except PriceGuideNotFound:
        raise not_found() from None
