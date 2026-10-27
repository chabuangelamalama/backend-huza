from sqlalchemy import Column, BigInteger, Numeric, String, Text, UniqueConstraint

from .base import Base, CreatedAtMixin, StrEnum, pg_enum, uuid_pk


class OsmType(StrEnum):
    NODE = "NODE"
    WAY = "WAY"
    RELATION = "RELATION"


osm_type_t = pg_enum(OsmType, "osm_type")


class Location(CreatedAtMixin, Base):
    __tablename__ = "location"

    location_id = uuid_pk()
    osm_type = Column(osm_type_t, nullable=False)
    osm_id = Column(BigInteger, nullable=False)
    name = Column(String(255), nullable=False)
    display_name = Column(Text, nullable=False)
    latitude = Column(Numeric(9, 6), nullable=False)
    longitude = Column(Numeric(9, 6), nullable=False)
    district = Column(String(100), nullable=False)
    province = Column(String(100), nullable=False)

    __table_args__ = (UniqueConstraint("osm_type", "osm_id", name="uq_locations_osm"),)
