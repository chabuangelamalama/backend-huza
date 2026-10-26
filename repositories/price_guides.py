import uuid
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from models import PriceGuide
from models.enums import Stream, Unit


class PriceGuideRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, **values: Any) -> PriceGuide:
        guide = PriceGuide(**values)
        self.db.add(guide)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(guide)
        return guide

    def get(self, guide_id: uuid.UUID) -> PriceGuide | None:
        return self.db.get(PriceGuide, guide_id)

    def search(
        self,
        *,
        stream: Stream | None = None,
        material: str | None = None,
        unit: Unit | None = None,
        district: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PriceGuide]:
        query = select(PriceGuide)
        if stream is not None:
            query = query.where(PriceGuide.stream == stream)
        if material:
            query = query.where(
                PriceGuide.material.icontains(material, autoescape=True)
            )
        if unit is not None:
            query = query.where(PriceGuide.unit == unit)
        if district:
            query = query.where(func.lower(PriceGuide.district) == district.lower())
        query = (
            query.order_by(
                PriceGuide.source_date.desc(),
                PriceGuide.material,
                PriceGuide.guide_id,
            )
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(query))

    def find_best(
        self,
        *,
        stream: Stream,
        material: str,
        unit: Unit,
        district: str | None = None,
    ) -> PriceGuide | None:
        query = select(PriceGuide).where(
            PriceGuide.stream == stream,
            func.lower(PriceGuide.material) == material.lower(),
            PriceGuide.unit == unit,
        )
        if district:
            wanted = district.lower()
            query = query.where(
                PriceGuide.district.is_(None)
                | (func.lower(PriceGuide.district) == wanted)
            )
            rank = case(
                (func.lower(PriceGuide.district) == wanted, 0),
                (PriceGuide.district.is_(None), 1),
                else_=2,
            )
        else:
            rank = case((PriceGuide.district.is_(None), 0), else_=1)
        query = query.order_by(
            rank, PriceGuide.source_date.desc(), PriceGuide.guide_id
        ).limit(1)
        return self.db.scalars(query).first()

    def update(self, guide: PriceGuide, changes: dict[str, Any]) -> PriceGuide:
        for name, value in changes.items():
            setattr(guide, name, value)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(guide)
        return guide

    def delete(self, guide: PriceGuide) -> None:
        self.db.delete(guide)
        self.db.commit()
