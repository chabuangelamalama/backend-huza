import logging
import uuid

from sqlalchemy import case, func, select, true
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from models.business import Business
from models.price_guide import PriceGuide
from models.user import User

logger = logging.getLogger("repositories")


def _narrow(column, wanted):
    if not wanted:
        return true(), case((column.is_(None), 0), else_=1)
    wanted = wanted.lower()
    allowed = column.is_(None) | (func.lower(column) == wanted)
    rank = case(
        (func.lower(column) == wanted, 0),
        (column.is_(None), 1),
        else_=2,
    )
    return allowed, rank


class PriceGuideRepository:
    def __init__(self):
        self.model = PriceGuide

    def get(self, db: Session, guide_id: uuid.UUID):
        return db.get(self.model, guide_id)

    def get_approval_status(self, db: Session, user_id: uuid.UUID):
        query = (
            select(Business.approval_status)
            .join(User, User.business_id == Business.business_id)
            .where(User.user_id == user_id)
        )
        return db.scalars(query).first()

    def search(
        self,
        db: Session,
        *,
        stream=None,
        material=None,
        grade=None,
        unit=None,
        district=None,
        limit: int = 50,
        offset: int = 0,
    ):
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
        stream,
        material,
        grade,
        district,
        exclude_id: uuid.UUID | None = None,
    ):
        query = select(self.model).where(
            self.model.stream == stream,
            func.lower(self.model.material) == material.lower(),
            self.model.grade.is_not_distinct_from(grade),
            func.lower(self.model.district).is_not_distinct_from(
                district.lower() if district else None
            ),
        )
        if exclude_id is not None:
            query = query.where(self.model.guide_id != exclude_id)
        return db.scalars(query).first()

    def find_best(
        self,
        db: Session,
        *,
        stream,
        material,
        unit,
        district=None,
        grade=None,
    ):
        district_allowed, district_rank = _narrow(self.model.district, district)
        grade_allowed, grade_rank = _narrow(self.model.grade, grade)
        query = (
            select(self.model)
            .where(
                self.model.stream == stream,
                func.lower(self.model.material) == material.lower(),
                self.model.unit == unit,
                district_allowed,
                grade_allowed,
            )
            .order_by(
                grade_rank,
                district_rank,
                self.model.source_date.desc(),
                self.model.guide_id,
            )
            .limit(1)
        )
        return db.scalars(query).first()

    def create(self, db: Session, data: dict):
        try:
            db_obj = self.model(**data)
            db.add(db_obj)
            db.commit()
            db.refresh(db_obj)
            return db_obj
        except SQLAlchemyError as error:
            logger.error("Could not create price guide: %s", error)
            db.rollback()
            raise

    def update(self, db: Session, db_obj, data: dict):
        try:
            for field, value in data.items():
                setattr(db_obj, field, value)
            db.commit()
            db.refresh(db_obj)
            return db_obj
        except SQLAlchemyError as error:
            logger.error("Could not update price guide: %s", error)
            db.rollback()
            raise

    def delete(self, db: Session, db_obj):
        try:
            db.delete(db_obj)
            db.commit()
        except SQLAlchemyError as error:
            logger.error("Could not delete price guide: %s", error)
            db.rollback()
            raise


price_guide_repository = PriceGuideRepository()
