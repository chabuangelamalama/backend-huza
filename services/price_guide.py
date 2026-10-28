import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.security import CurrentUser
from models import PriceGuide
from models.business import ApprovalStatus
from models.listing import Stream, Unit
from repositories.price_guide import price_guide_repository
from schemas.price_guide import (
    Position,
    PriceCheck,
    PriceGuideCreate,
    PriceGuideRead,
    PriceGuideUpdate,
    check_grade,
    check_range,
)

NULLABLE_FIELDS = {"grade", "sample_size", "district"}
DUPLICATE_FIELDS = {"stream", "material", "grade", "district"}


def _role_of(current_user: CurrentUser) -> str:
    role = current_user.role
    return str(getattr(role, "value", role)).upper()


def _authorise(
    db: Session,
    current_user: CurrentUser,
    action: str,
    admin_only: bool = False,
) -> None:
    role = _role_of(current_user)
    allowed_roles = {"ADMIN"} if admin_only else {"ADMIN", "BUSINESS_USER"}

    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: a {role.lower()} cannot {action}.",
        )

    if role == "BUSINESS_USER":
        approval = price_guide_repository.get_approval_status(db, current_user.user_id)
        if approval != ApprovalStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Access denied: your business is not approved, "
                    f"so you cannot {action}."
                ),
            )


def _find_guide(db: Session, guide_id: uuid.UUID) -> PriceGuide:
    guide = price_guide_repository.get(db, guide_id)
    if guide is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Price guide not found.",
        )
    return guide


def _reject_duplicate(
    db: Session,
    values: dict[str, Any],
    exclude_id: uuid.UUID | None = None,
) -> None:
    found = price_guide_repository.find_duplicate(db, exclude_id=exclude_id, **values)
    if found is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A price guide for this stream, material, grade and district "
                "already exists. Update it instead."
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


class PriceGuideService:
    def present(self, guide: PriceGuide, current_user: CurrentUser) -> PriceGuideRead:
        read = PriceGuideRead.model_validate(guide)
        if _role_of(current_user) != "ADMIN":
            read.created_by = None
        return read

    def list_price_guides(
        self,
        db: Session,
        current_user: CurrentUser,
        **filters: Any,
    ):
        _authorise(db, current_user, "view price guides")
        return price_guide_repository.search(db, **filters)

    def get_price_guide(
        self,
        db: Session,
        guide_id: uuid.UUID,
        current_user: CurrentUser,
    ):
        _authorise(db, current_user, "view price guides")
        return _find_guide(db, guide_id)

    def create_price_guide(
        self,
        db: Session,
        data: PriceGuideCreate,
        current_user: CurrentUser,
    ):
        _authorise(db, current_user, "create price guides", admin_only=True)

        guide_data = data.model_dump()
        _reject_duplicate(db, {name: guide_data[name] for name in DUPLICATE_FIELDS})
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
        _authorise(db, current_user, "update price guides", admin_only=True)

        guide = _find_guide(db, guide_id)

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

        merged = {
            name: changes[name] if name in changes else getattr(guide, name)
            for name in DUPLICATE_FIELDS
        }

        try:
            check_range(
                changes.get("min_price", guide.min_price),
                changes.get("max_price", guide.max_price),
            )
            if "stream" in changes or "grade" in changes:
                check_grade(merged["stream"], merged["grade"])
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

        if DUPLICATE_FIELDS & changes.keys():
            _reject_duplicate(db, merged, exclude_id=guide.guide_id)

        return price_guide_repository.update(db, guide, changes)

    def delete_price_guide(
        self,
        db: Session,
        guide_id: uuid.UUID,
        current_user: CurrentUser,
    ):
        _authorise(db, current_user, "delete price guides", admin_only=True)
        guide = _find_guide(db, guide_id)
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
        _authorise(db, current_user, "look up prices")

        guide = price_guide_repository.find_best(
            db,
            stream=stream,
            material=material,
            unit=unit,
            district=district,
            grade=grade.lower() if grade else None,
        )

        if guide is None:
            return PriceCheck(guide=None, position=None)

        return PriceCheck(
            guide=self.present(guide, current_user),
            position=_position_of(price, guide),
        )


price_guide_service = PriceGuideService()
