from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MpesaSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MPESA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["sandbox", "production"] = "sandbox"

    mode: Literal["live", "simulated"] = "live"

    simulator_delay_seconds: float = Field(default=5.0, ge=0)

    base_url: str | None = None

    currency: str = "KES"

    consumer_key: SecretStr = SecretStr("")
    consumer_secret: SecretStr = SecretStr("")

    express_shortcode: str = ""
    express_passkey: SecretStr = SecretStr("")

    callback_secret: SecretStr = SecretStr("")

    b2c_shortcode: str = ""
    initiator_name: str = ""
    security_credential: SecretStr = SecretStr("")

    callback_base_url: str = ""

    http_timeout_seconds: float = Field(default=30.0, gt=0)

    max_attempts_per_enquiry: int = Field(default=5, ge=1)

    attempt_cooldown_seconds: int = Field(default=30, ge=0)

    max_attempts_per_business_per_hour: int = Field(default=10, ge=1)

    max_attempts_per_payer_phone_per_hour: int = Field(default=5, ge=1)

    status_poll_min_interval_seconds: int = Field(default=5, ge=1)

    payout_trigger: Literal["ON_COMPLETED", "ON_PAID"] = "ON_COMPLETED"

    auto_release_days: int = Field(default=7, ge=1, le=60)

    auto_payout: bool = True

    huza_fee_percent: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=50,
    )

    require_registered_payer_phone: bool = True

    payout_change_hold_hours: int = Field(default=24, ge=0, le=720)

    auto_refund_on_conflict: bool = True

    stale_pending_review_hours: int = Field(default=24, ge=1)

    @property
    def shortcode(self) -> str:
        return self.express_shortcode

    @property
    def passkey(self) -> SecretStr:
        return self.express_passkey

    @property
    def timeout(self) -> float:
        return self.http_timeout_seconds

    @property
    def transaction_type(self) -> str:
        return "CustomerPayBillOnline"

    @model_validator(mode="after")
    def validate_mpesa_settings(self) -> "MpesaSettings":

        expected_base_url = (
            "https://api.safaricom.co.ke"
            if self.environment == "production"
            else "https://sandbox.safaricom.co.ke"
        )

        if self.base_url is None:
            self.base_url = expected_base_url

        if not self.base_url.startswith("https://"):
            raise ValueError("MPESA_BASE_URL must use HTTPS")

        if self.mode == "live":
            if self.base_url.rstrip("/") != expected_base_url:
                raise ValueError("MPESA_BASE_URL does not match MPESA_ENVIRONMENT")

        if self.currency != "KES":
            raise ValueError("MPESA_CURRENCY must be KES")

        if self.mode == "live":
            problems = []

            if not self.consumer_key.get_secret_value():
                problems.append("MPESA_CONSUMER_KEY is missing")

            if not self.consumer_secret.get_secret_value():
                problems.append("MPESA_CONSUMER_SECRET is missing")

            if not self.express_passkey.get_secret_value():
                problems.append("MPESA_EXPRESS_PASSKEY is missing")

            if not self.express_shortcode.strip():
                problems.append("MPESA_EXPRESS_SHORTCODE is missing")

            if not self.callback_secret.get_secret_value():
                problems.append("MPESA_CALLBACK_SECRET is missing")

            if not self.callback_base_url.startswith("https://"):
                problems.append("MPESA_CALLBACK_BASE_URL must be a public HTTPS URL")

            if problems:
                raise ValueError("; ".join(problems))

        if self.callback_base_url:
            self.callback_base_url = self.callback_base_url.rstrip("/")

        return self


@lru_cache
def get_mpesa_settings() -> MpesaSettings:
    return MpesaSettings()
