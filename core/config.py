"""Application settings, read from environment variables and the .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_SECRET_PREFIX = "replace-with"


def normalize_database_url(url: str) -> str:
    """Always use the psycopg2 driver. Heroku hands out postgres:// URLs, which
    SQLAlchemy 2 no longer understands."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    jwt_secret: str = Field(min_length=32)

    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_minutes: int = Field(default=30, gt=0)
    reset_token_minutes: int = Field(default=60, gt=0)
    verify_token_minutes: int = Field(default=1440, gt=0)  # 24 hours
    max_failed_logins: int = Field(default=5, gt=0)
    lockout_minutes: int = Field(default=15, gt=0)

    environment: Literal["development", "test", "production"] = "development"
    cors_origins: str = ""
    password_reset_url: str = "huza://reset-password"
    email_verify_url: str = "huza://verify-email"

    # --- Email & SMTP configuration ---
    email_from: str = "onboarding@resend.dev"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True

    @field_validator("database_url")
    @classmethod
    def _normalize_url(cls, value: str) -> str:
        return normalize_database_url(value.strip())

    @model_validator(mode="after")
    def _reject_placeholder_secret_in_production(self) -> "Settings":
        if self.is_production and self.jwt_secret.startswith(PLACEHOLDER_SECRET_PREFIX):
            raise ValueError("JWT_SECRET is still the placeholder; set a real secret")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
