import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from models import PriceGuide
from models.listing import Stream, Unit

logger = logging.getLogger("repositories")


class PriceGuideRepository:
    def __init__(self):
        self.model = PriceGuide

    def get(self, db: Session, guide_id: uuid.UUID) -> PriceGuide | None:
        return db.get(self.model, guide_id)

    def search(
        self,
        db: Session,
        *,
        stream: Stream | None = None,
        material: str | None = None,
        grade: str | None = None,
        unit: Unit | None = None,
        district: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PriceGuide]:
        query = select(self.model)
        if stream is not None:
            query = query.where(self.model.stream == stream)
        if material:
            query = query.where(
                self.model.material.icontains(material, autoescape=True)
            )
        if grade:
            query = query.where(func.lower(self.model.grade) == grade.lower())
        if unit is not None:
            query = query.where(self.model.unit == unit)
        if district:
            query = query.where(func.lower(self.model.district) == district.lower())
        query = (
            query.order_by(
                self.model.source_date.desc(),
                self.model.material,
                self.model.guide_id,
            )
            .limit(limit)
            .offset(offset)
        )
        return list(db.scalars(query))

    def find_duplicate(
        self,
        db: Session,
        *,
        stream: Stream,
        material: str,
        grade: str | None,
        unit: Unit,
        district: str | None,
        source_date: date,
        exclude_id: uuid.UUID | None = None,
    ) -> PriceGuide | None:
        query = select(self.model).where(
            self.model.stream == stream,
            func.lower(self.model.material) == material.lower(),
            self.model.grade.is_not_distinct_from(grade),
            self.model.unit == unit,
            func.lower(self.model.district).is_not_distinct_from(
                district.lower() if district else None
            ),
            self.model.source_date == source_date,
        )
        if exclude_id is not None:
            query = query.where(self.model.guide_id != exclude_id)
        return db.scalars(query.limit(1)).first()

    def find_best(
        self,
        db: Session,
        *,
        stream: Stream,
        material: str,
        unit: Unit,
        district: str | None = None,
        grade: str | None = None,
    ) -> PriceGuide | None:
        query = select(self.model).where(
            self.model.stream == stream,
            func.lower(self.model.material) == material.lower(),
            self.model.unit == unit,
        )
        if grade:
            wanted_grade = grade.lower()
            query = query.where(
                self.model.grade.is_(None)
                | (func.lower(self.model.grade) == wanted_grade)
            )
            grade_rank = case(
                (func.lower(self.model.grade) == wanted_grade, 0),
                else_=1,
            )
        else:
            grade_rank = case((self.model.grade.is_(None), 0), else_=1)
        if district:
            wanted = district.lower()
            query = query.where(
                self.model.district.is_(None)
                | (func.lower(self.model.district) == wanted)
            )
            rank = case(
                (func.lower(self.model.district) == wanted, 0),
                (self.model.district.is_(None), 1),
                else_=2,
            )
        else:
            rank = case((self.model.district.is_(None), 0), else_=1)
        query = query.order_by(
            grade_rank, rank, self.model.source_date.desc(), self.model.guide_id
        ).limit(1)
        return db.scalars(query).first()

    def create(self, db: Session, data: dict[str, Any]) -> PriceGuide:
        try:
            guide = self.model(**data)
            db.add(guide)
            db.commit()
            db.refresh(guide)
            return guide
        except SQLAlchemyError as e:
            logger.error(f"Failed to create PriceGuide: {str(e)}")
            db.rollback()
            raise

    def update(
        self, db: Session, db_obj: PriceGuide, data: dict[str, Any]
    ) -> PriceGuide:
        guide_id = db_obj.guide_id
        try:
            data.pop("guide_id", None)
            for field, value in data.items():
                setattr(db_obj, field, value)
            db.commit()
            db.refresh(db_obj)
            return db_obj
        except SQLAlchemyError as e:
            logger.error(f"Failed to update PriceGuide {guide_id}: {str(e)}")
            db.rollback()
            raise

    def delete(self, db: Session, db_obj: PriceGuide) -> None:
        guide_id = db_obj.guide_id
        try:
            db.delete(db_obj)
            db.commit()
        except SQLAlchemyError as e:
            logger.error(f"Failed to delete PriceGuide {guide_id}: {str(e)}")
            db.rollback()
            raise


price_guide_repository = PriceGuideRepository()