from sqlalchemy import Column, CheckConstraint, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, StrEnum, TimestampMixin, pg_enum, uuid_pk


class UserRole(StrEnum):
    BUSINESS_USER = "BUSINESS_USER"
    ADMIN = "ADMIN"


user_role_t = pg_enum(UserRole, "user_role")


class User(TimestampMixin, Base):
    __tablename__ = "app_user"

    user_id = uuid_pk()
    business_id = Column(
        UUID(as_uuid=True),
        ForeignKey("business.business_id", ondelete="RESTRICT"),
        unique=True,
        nullable=True,
    )
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(Text, nullable=False, unique=True)
    phone = Column(Text, nullable=True)
    password_hash = Column(String(255), nullable=False)
    user_role = Column(
        user_role_t,
        nullable=False,
        default=UserRole.BUSINESS_USER,
        server_default=text("'BUSINESS_USER'"),
    )

    __table_args__ = (
        CheckConstraint(
            "(user_role = 'ADMIN') = (business_id IS NULL)",
            name="user_role_business",
        ),
    )
    business = relationship(
        "Business", back_populates="user", foreign_keys=[business_id]
    )
