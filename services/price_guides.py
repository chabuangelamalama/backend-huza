import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError

from models import PriceGuide
from models.enums import Stream, Unit
from schemas.price_guides import Position, PriceGuideCreate, PriceGuideUpdate

NULLABLE_FIELDS = {"grade", "sample_size", "district"}


class PriceGuideNotFound(Exception):
    pass


class InvalidPriceRange(Exception):
    pass


class UnknownUser(Exception):
    pass


def position_of(price: Decimal | None, guide: PriceGuide | None) -> Position | None:
    if price is None or guide is None:
        return None
    if price < guide.min_price:
        return "below"
    if price > guide.max_price:
        return "above"
    return "within"


class PriceGuideService:
    def __init__(self, repository: Any):
        self.repository = repository

    def create(self, data: PriceGuideCreate, user_id: uuid.UUID) -> PriceGuide:
        try:
            return self.repository.add(**data.model_dump(), created_by=user_id)
        except IntegrityError:
            raise UnknownUser from None

    def get(self, guide_id: uuid.UUID) -> PriceGuide:
        guide = self.repository.get(guide_id)
        if guide is None:
            raise PriceGuideNotFound
        return guide

    def list(self, **filters: Any) -> list[PriceGuide]:
        return self.repository.search(**filters)

    def update(self, guide_id: uuid.UUID, data: PriceGuideUpdate) -> PriceGuide:
        guide = self.get(guide_id)
        changes = {
            name: value
            for name, value in data.model_dump(exclude_unset=True).items()
            if value is not None or name in NULLABLE_FIELDS
        }
        new_min = changes.get("min_price", guide.min_price)
        new_max = changes.get("max_price", guide.max_price)
        if new_max < new_min:
            raise InvalidPriceRange
        return self.repository.update(guide, changes)

    def delete(self, guide_id: uuid.UUID) -> None:
        self.repository.delete(self.get(guide_id))

    def check(
        self,
        *,
        stream: Stream,
        material: str,
        unit: Unit,
        price: Decimal | None = None,
        district: str | None = None,
    ) -> tuple[PriceGuide | None, Position | None]:
        guide = self.repository.find_best(
            stream=stream, material=material, unit=unit, district=district
        )
        return guide, position_of(price, guide)
