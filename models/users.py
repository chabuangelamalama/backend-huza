import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, uuid_pk
from .enums import UserRole, user_role_t

if TYPE_CHECKING:
    from .businesses import Business


class User(TimestampMixin, Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = uuid_pk()
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.business_id", ondelete="RESTRICT"),
        unique=True,
        nullable=True,
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    user_role: Mapped[UserRole] = mapped_column(
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
    business: Mapped["Business | None"] = relationship(
        "Business", back_populates="user", foreign_keys=[business_id]
    )
