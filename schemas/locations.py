import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.location import OsmType
from schemas.common import Coordinate, Text, Text100, Text255


class LocationCreate(BaseModel):
    osm_type: OsmType
    osm_id: int = Field(gt=0)
    name: Text255
    display_name: Text
    latitude: Decimal = Field(ge=-90, le=90, max_digits=9, decimal_places=6)
    longitude: Decimal = Field(ge=-180, le=180, max_digits=9, decimal_places=6)
    sub_county: Text100
    county: Text100

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


class LocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: uuid.UUID
    osm_type: OsmType
    osm_id: int
    name: str
    display_name: str
    latitude: Coordinate
    longitude: Coordinate
    sub_county: str
    county: str
    created_at: datetime


class LocationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: uuid.UUID
    name: str
    sub_county: str
    county: str


class PlaceResult(BaseModel):
    osm_type: OsmType
    osm_id: int
    name: str
    display_name: str
    latitude: Coordinate
    longitude: Coordinate
    sub_county: str
    county: str
