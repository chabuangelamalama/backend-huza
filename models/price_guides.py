import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, uuid_pk
from .enums import Stream, Unit, stream_t, unit_t

if TYPE_CHECKING:
    from .users import User


class PriceGuide(TimestampMixin, Base):
    __tablename__ = "price_guides"

    guide_id: Mapped[uuid.UUID] = uuid_pk()
    stream: Mapped[Stream] = mapped_column(stream_t, nullable=False)
    material: Mapped[str] = mapped_column(String(150), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[Unit] = mapped_column(unit_t, nullable=False)
    min_price: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    max_price: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    source_date: Mapped[date] = mapped_column(Date, nullable=False)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("min_price > 0", name="min_price_positive"),
        CheckConstraint("max_price >= min_price", name="price_range_order"),
    )

    creator: Mapped["User | None"] = relationship("User")
