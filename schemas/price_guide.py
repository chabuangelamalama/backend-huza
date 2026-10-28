import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from models.listing import Stream, Unit

Position = Literal["below", "within", "above"]
PriceField = Field(gt=0, max_digits=19, decimal_places=4)


class PriceGuideFields(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    stream: Stream
    material: str = Field(min_length=1, max_length=150)
    grade: str | None = Field(default=None, max_length=100)
    unit: Unit
    min_price: Decimal = PriceField
    max_price: Decimal = PriceField
    source: str = Field(min_length=1, max_length=255)
    source_date: date
    sample_size: int | None = Field(default=None, ge=1)
    district: str | None = Field(default=None, max_length=100)


class PriceGuideCreate(PriceGuideFields):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class PriceGuideUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    stream: Stream | None = None
    material: str | None = Field(default=None, min_length=1, max_length=150)
    grade: str | None = Field(default=None, max_length=100)
    unit: Unit | None = None
    min_price: Decimal | None = Field(
        default=None, gt=0, max_digits=19, decimal_places=4
    )
    max_price: Decimal | None = Field(
        default=None, gt=0, max_digits=19, decimal_places=4
    )
    source: str | None = Field(default=None, min_length=1, max_length=255)
    source_date: date | None = None
    sample_size: int | None = Field(default=None, ge=1)
    district: str | None = Field(default=None, max_length=100)


class PriceGuideRead(PriceGuideFields):
    model_config = ConfigDict(from_attributes=True)

    guide_id: uuid.UUID
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class PriceCheck(BaseModel):
    guide: PriceGuideRead | None
    position: Position | None
