from sqlalchemy import (
    Column,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, StrEnum, TimestampMixin, uuid_pk
from .listing import Stream, stream_t, unit_t


class SawdustGrade(StrEnum):
    DRY = "dry"
    WET = "wet"


class PlasticGrade(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class GarmentGrade(StrEnum):
    COTTON = "cotton"
    SYNTHETIC = "synthetic"
    MIXED = "mixed"


class GlassGrade(StrEnum):
    CLEAR = "clear"
    AMBER = "amber"
    GREEN = "green"


GRADES_BY_STREAM = {
    Stream.SAWDUST: {grade.value for grade in SawdustGrade},
    Stream.PLASTIC: {grade.value for grade in PlasticGrade},
    Stream.GARMENT_OFFCUTS: {grade.value for grade in GarmentGrade},
    Stream.GLASS: {grade.value for grade in GlassGrade},
}


class PriceGuide(TimestampMixin, Base):
    __tablename__ = "price_guide"

    guide_id = uuid_pk()
    stream = Column(stream_t, nullable=False)
    material = Column(String(150), nullable=False)
    grade = Column(String(100), nullable=True)
    unit = Column(unit_t, nullable=False)
    min_price = Column(Numeric(19, 4), nullable=False)
    max_price = Column(Numeric(19, 4), nullable=False)
    source = Column(String(255), nullable=False)
    source_date = Column(Date, nullable=False)
    sample_size = Column(Integer, nullable=True)
    district = Column(String(100), nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("min_price > 0", name="min_price_positive"),
        CheckConstraint("max_price >= min_price", name="price_range_order"),
    )

    creator = relationship("User")
