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

from models.listing import Stream, Unit
from models.price_guide import GRADES_BY_STREAM

Position = Literal["below", "within", "above"]

PriceField = Field(gt=0, max_digits=19, decimal_places=4)


def reject_future_date(value: date | None) -> date | None:
    if value is not None and value > date.today():
        raise ValueError("Source date cannot be in the future")
    return value


def lowercase_grade(value: str | None) -> str | None:
    if value is None:
        return None
    return value.lower()


def check_grade(stream: Stream, grade: str | None) -> None:
    if grade is None:
        return
    allowed = GRADES_BY_STREAM[stream]
    if grade not in allowed:
        options = ", ".join(sorted(allowed))
        raise ValueError(
            f"Grade '{grade}' is not valid for {stream.value}. "
            f"Allowed grades: {options}"
        )


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

    @field_validator("grade")
    @classmethod
    def normalise_grade(cls, value: str | None) -> str | None:
        return lowercase_grade(value)

    @field_validator("source_date")
    @classmethod
    def source_date_not_in_future(cls, value: date) -> date:
        return reject_future_date(value)

    @model_validator(mode="after")
    def max_price_not_below_min_price(self) -> "PriceGuideCreate":
        if self.max_price < self.min_price:
            raise ValueError("Max price cannot be below min price")
        return self

    @model_validator(mode="after")
    def grade_matches_stream(self) -> "PriceGuideCreate":
        check_grade(self.stream, self.grade)
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

    @field_validator("grade")
    @classmethod
    def normalise_grade(cls, value: str | None) -> str | None:
        return lowercase_grade(value)

    @field_validator("source_date")
    @classmethod
    def source_date_not_in_future(cls, value: date | None) -> date | None:
        return reject_future_date(value)

    @model_validator(mode="after")
    def grade_matches_stream(self) -> "PriceGuideUpdate":
        if self.stream is not None and self.grade is not None:
            check_grade(self.stream, self.grade)
        return self


class PriceGuideRead(PriceGuideFields):
    model_config = ConfigDict(from_attributes=True)

    guide_id: uuid.UUID
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class PriceCheck(BaseModel):
    guide: PriceGuideRead | None
    position: Position | None
    is_outdated: bool = False
    message: str | None = None