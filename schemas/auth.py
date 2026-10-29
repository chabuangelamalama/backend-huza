import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from models.business import ApprovalStatus, BusinessRole
from models.user import UserRole

PASSWORD_RULE = "Use at least 8 characters with a number."


def _check_password_rules(value: str) -> str:
    if len(value) < 8 or not any(ch.isdigit() for ch in value):
        raise ValueError(PASSWORD_RULE)
    return value


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


class BusinessSummary(BaseModel):
    """Enough for the app to decide which screen to show after sign-in
    (under review, approved, rejected, suspended)."""

    model_config = ConfigDict(from_attributes=True)

    business_id: uuid.UUID
    display_name: str | None
    business_role: BusinessRole
    approval_status: ApprovalStatus


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    user_id: uuid.UUID
    business_id: uuid.UUID | None
    first_name: str
    last_name: str
    email: str
    phone: str | None
    role: UserRole = Field(validation_alias="user_role")
    mfa_enabled: bool
    created_at: datetime
    updated_at: datetime
    business: BusinessSummary | None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: UserOut


class MessageResponse(BaseModel):
    detail: str


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(max_length=128)

    @model_validator(mode="after")
    def _strong_password(self) -> "ResetPasswordRequest":
        _check_password_rules(self.password)
        return self


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(max_length=128)

    @model_validator(mode="after")
    def _validate(self) -> "ChangePasswordRequest":
        _check_password_rules(self.new_password)
        if self.new_password == self.current_password:
            raise ValueError("The new password must be different from the current one.")
        return self
