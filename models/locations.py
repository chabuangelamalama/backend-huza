import uuid
from decimal import Decimal

from sqlalchemy import BigInteger, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, uuid_pk
from .enums import OsmType, osm_type_t


class Location(CreatedAtMixin, Base):
    __tablename__ = "locations"

    location_id: Mapped[uuid.UUID] = uuid_pk()
    osm_type: Mapped[OsmType] = mapped_column(osm_type_t, nullable=False)
    osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    district: Mapped[str] = mapped_column(String(100), nullable=False)
    province: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (UniqueConstraint("osm_type", "osm_id", name="uq_locations_osm"),)
