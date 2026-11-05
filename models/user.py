from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, StrEnum, TimestampMixin, pg_enum, timestamptz, uuid_pk


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

    token_version = Column(Integer, nullable=False, default=0, server_default=text("0"))

    failed_login_attempts = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    locked_until = timestamptz(nullable=True)

    mfa_secret_enc = Column(Text, nullable=True)
    mfa_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    last_totp_step = Column(BigInteger, nullable=True)

    # 6-digit OTP reset fields
    reset_code_hash = Column(String(255), nullable=True)
    reset_code_expires_at = timestamptz(nullable=True)

    email_verified_at = timestamptz(nullable=True)
    verify_code_hash = Column(String(255), nullable=True)
    verify_code_expires_at = timestamptz(nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(user_role = 'ADMIN') = (business_id IS NULL)",
            name="user_role_business",
        ),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint(
            "failed_login_attempts >= 0", name="failed_login_attempts_non_negative"
        ),
        CheckConstraint(
            "mfa_enabled = false OR mfa_secret_enc IS NOT NULL",
            name="mfa_secret_required",
        ),
    )
    business = relationship(
        "Business", back_populates="user", foreign_keys=[business_id]
    )

    @property
    def role(self) -> UserRole:
        """Same as user_role; lets services treat User and CurrentUser alike."""
        return self.user_role
