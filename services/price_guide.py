import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.security import CurrentUser
from models import PriceGuide
from models.listing import Stream, Unit
from repositories.price_guide import price_guide_repository
from schemas.price_guide import (
    Position,
    PriceCheck,
    PriceGuideCreate,
    PriceGuideRead,
    PriceGuideUpdate,
    check_grade,
)

NULLABLE_FIELDS = {"grade", "sample_size", "district"}
DUPLICATE_FIELDS = {"stream", "material", "grade", "unit", "district", "source_date"}
READ_ROLES = {"ADMIN", "BUSINESS_USER"}
STALE_AFTER_DAYS = 180


def _role_of(current_user: CurrentUser) -> str:
    role = current_user.role
    return str(getattr(role, "value", role)).upper()


def _require_reader(current_user: CurrentUser) -> None:
    if _role_of(current_user) not in READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Your account cannot view price guides.",
        )


def _require_editor(current_user: CurrentUser) -> None:
    if _role_of(current_user) != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Only an admin can change price guides.",
        )


def _get_or_404(db: Session, guide_id: uuid.UUID) -> PriceGuide:
    guide = price_guide_repository.get(db, guide_id)
    if guide is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Price guide not found.",
        )
    return guide


def _reject_duplicate(
    db: Session,
    *,
    stream: Stream,
    material: str,
    grade: str | None,
    unit: Unit,
    district: str | None,
    source_date: date,
    exclude_id: uuid.UUID | None = None,
) -> None:
    found = price_guide_repository.find_duplicate(
        db,
        stream=stream,
        material=material,
        grade=grade,
        unit=unit,
        district=district,
        source_date=source_date,
        exclude_id=exclude_id,
    )
    if found is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A price guide with the same stream, material, grade, unit, "
                "district and source date already exists."
            ),
        )


def _position_of(price: Decimal | None, guide: PriceGuide | None) -> Position | None:
    if price is None or guide is None:
        return None
    if price < guide.min_price:
        return "below"
    if price > guide.max_price:
        return "above"
    return "within"


def _money(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _describe(position: Position | None, guide: PriceGuide, outdated: bool) -> str:
    usual = f"{_money(guide.min_price)} to {_money(guide.max_price)}"
    if position == "below":
        text = f"Your price is below the usual range of {usual}."
    elif position == "above":
        text = f"Your price is above the usual range of {usual}."
    elif position == "within":
        text = f"Your price is within the usual range of {usual}."
    else:
        text = f"The usual range is {usual}."
    if outdated:
        text += " This guide is over 6 months old, so prices may have changed."
    return text


class PriceGuideService:

    def list_price_guides(
        self,
        db: Session,
        current_user: CurrentUser,
        **filters: Any,
    ):
        _require_reader(current_user)
        return price_guide_repository.search(db, **filters)

    def get_price_guide(
        self,
        db: Session,
        guide_id: uuid.UUID,
        current_user: CurrentUser,
    ):
        _require_reader(current_user)
        return _get_or_404(db, guide_id)

    def create_price_guide(
        self,
        db: Session,
        data: PriceGuideCreate,
        current_user: CurrentUser,
    ):
        _require_editor(current_user)

        _reject_duplicate(
            db,
            stream=data.stream,
            material=data.material,
            grade=data.grade,
            unit=data.unit,
            district=data.district,
            source_date=data.source_date,
        )

        guide_data = data.model_dump()
        guide_data["created_by"] = current_user.user_id

        try:
            return price_guide_repository.create(db, guide_data)
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your login is not valid.",
            ) from None

    def update_price_guide(
        self,
        db: Session,
        guide_id: uuid.UUID,
        data: PriceGuideUpdate,
        current_user: CurrentUser,
    ):
        _require_editor(current_user)

        guide = _get_or_404(db, guide_id)

        changes = {
            name: value
            for name, value in data.model_dump(exclude_unset=True).items()
            if value is not None or name in NULLABLE_FIELDS
        }

        if not changes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nothing to update. Send at least one field.",
            )

        new_min = changes.get("min_price", guide.min_price)
        new_max = changes.get("max_price", guide.max_price)

        if new_max < new_min:
            raise HTTPException(
                status_code=422,
                detail="Max price cannot be below min price.",
            )

        merged = {
            name: changes[name] if name in changes else getattr(guide, name)
            for name in DUPLICATE_FIELDS
        }

        if "stream" in changes or "grade" in changes:
            try:
                check_grade(merged["stream"], merged["grade"])
            except ValueError as error:
                raise HTTPException(
                    status_code=422,
                    detail=str(error),
                ) from None

        if DUPLICATE_FIELDS & changes.keys():
            _reject_duplicate(db, **merged, exclude_id=guide.guide_id)

        return price_guide_repository.update(db, guide, changes)

    def delete_price_guide(
        self,
        db: Session,
        guide_id: uuid.UUID,
        current_user: CurrentUser,
    ):
        _require_editor(current_user)
        guide = _get_or_404(db, guide_id)
        price_guide_repository.delete(db, guide)

    def check_price(
        self,
        db: Session,
        current_user: CurrentUser,
        *,
        stream: Stream,
        material: str,
        unit: Unit,
        grade: str | None = None,
        price: Decimal | None = None,
        district: str | None = None,
    ) -> PriceCheck:
        _require_reader(current_user)

        guide = price_guide_repository.find_best(
            db,
            stream=stream,
            material=material,
            unit=unit,
            district=district,
            grade=grade.lower() if grade else None,
        )

        if guide is None:
            return PriceCheck(
                guide=None,
                position=None,
                message="No price guide found for this material.",
            )

        outdated = guide.source_date < date.today() - timedelta(
            days=STALE_AFTER_DAYS
        )
        position = _position_of(price, guide)

        return PriceCheck(
            guide=PriceGuideRead.model_validate(guide),
            position=position,
            is_outdated=outdated,
            message=_describe(position, guide, outdated),
        )


price_guide_service = PriceGuideService()