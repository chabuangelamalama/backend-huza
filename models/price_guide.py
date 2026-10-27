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

from .base import Base, TimestampMixin, uuid_pk
from .listing import stream_t, unit_t


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
