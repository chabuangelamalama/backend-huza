import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from models.enums import Stream, Unit

Position = Literal["below", "within", "above"]

PriceField = Field(gt=0, max_digits=19, decimal_places=4)


def reject_future_date(value: date | None) -> date | None:
    if value is not None and value > date.today():
        raise ValueError("Source date cannot be in the future")
    return value


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

    @field_validator("source_date")
    @classmethod
    def source_date_not_in_future(cls, value: date) -> date:
        return reject_future_date(value)

    @model_validator(mode="after")
    def max_price_not_below_min_price(self) -> "PriceGuideCreate":
        if self.max_price < self.min_price:
            raise ValueError("Max price cannot be below min price")
        return self


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

    @field_validator("source_date")
    @classmethod
    def source_date_not_in_future(cls, value: date | None) -> date | None:
        return reject_future_date(value)


class PriceGuideRead(PriceGuideFields):
    model_config = ConfigDict(from_attributes=True)

    guide_id: uuid.UUID
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class PriceCheck(BaseModel):
    guide: PriceGuideRead | None
    position: Position | None
