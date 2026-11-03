from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field, field_serializer, field_validator

from models.location import OsmType
from schemas.common import clean_text


class LocationCreate(BaseModel):
    osm_type: OsmType
    osm_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1)
    latitude: Decimal = Field(ge=-90, le=90, max_digits=9, decimal_places=6)
    longitude: Decimal = Field(ge=-180, le=180, max_digits=9, decimal_places=6)
    sub_county: str = Field(min_length=1, max_length=100)
    county: str = Field(min_length=1, max_length=100)

    @field_validator("name", "display_name", "sub_county", "county", mode="before")
    @classmethod
    def tidy_text(cls, value: object) -> object:
        return clean_text(value)

    @field_validator("osm_type", mode="before")
    @classmethod
    def upper_osm_type(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def round_coordinate(cls, value: object) -> object:
        if not isinstance(value, (int, float, str, Decimal)):
            return value
        try:
            return Decimal(str(value)).quantize(Decimal("0.000001"))
        except InvalidOperation:
            return value


class PlaceResult(BaseModel):
    osm_type: OsmType
    osm_id: int
    name: str
    display_name: str
    latitude: Decimal
    longitude: Decimal
    sub_county: str
    county: str

    @field_serializer("latitude", "longitude", when_used="json")
    def as_number(self, value: Decimal) -> float:
        return float(value)
