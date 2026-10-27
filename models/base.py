import enum

from sqlalchemy import Column, DateTime, Enum as SAEnum, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk():
    return Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def timestamptz(**kwargs):
    return Column(DateTime(timezone=True), **kwargs)


class CreatedAtMixin:
    created_at = timestamptz(nullable=False, server_default=func.now())


class TimestampMixin(CreatedAtMixin):
    updated_at = timestamptz(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:
        return self.value


def pg_enum(cls: type[enum.Enum], name: str) -> SAEnum:
    return SAEnum(
        cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
