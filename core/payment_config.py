from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MpesaSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MPESA_", env_file=".env", extra="ignore"
    )

    environment: Literal["sandbox", "production"] = "sandbox"

    mode: Literal["live", "simulated"] = "live"
    simulator_delay_seconds: float = 5.0
    base_url: str = "https://safaricom.co.ke"

    currency: str = "KES"

    consumer_key: SecretStr = SecretStr("")
    consumer_secret: SecretStr = SecretStr("")
    express_shortcode: str = ""
    express_passkey: SecretStr = SecretStr("")

    callback_base_url: str = ""

    http_timeout_seconds: float = 15.0

    max_attempts_per_enquiry: int = 5
    attempt_cooldown_seconds: int = 30
    max_attempts_per_business_per_hour: int = 10
    max_attempts_per_payer_phone_per_hour: int = 5
    status_poll_min_interval_seconds: int = 5

    payout_trigger: Literal["ON_COMPLETED", "ON_PAID"] = "ON_COMPLETED"
    auto_release_days: int = Field(default=7, ge=1, le=60)

    auto_payout: bool = True

    huza_fee_percent: Decimal = Field(default=Decimal("0"), ge=0, le=50)

    require_registered_payer_phone: bool = True

    payout_change_hold_hours: int = Field(default=24, ge=0, le=720)

    auto_refund_on_conflict: bool = True

    stale_pending_review_hours: int = Field(default=24, ge=1)

    @model_validator(mode="after")
    def _validate(self) -> "MpesaSettings":
        if self.environment == "production":
            problems = []
            if self.mode != "live":
                problems.append("MPESA_MODE must be live in production")
            if not self.base_url.startswith("https://"):
                problems.append("MPESA_BASE_URL must be https")
            if self.currency != "KES":
                problems.append("MPESA_CURRENCY must be KES in production")
            if not self.callback_base_url.startswith("https://"):
                problems.append("MPESA_CALLBACK_BASE_URL must be https")
            for name in (
                "consumer_key",
                "consumer_secret",
                "express_passkey",
            ):
                if not getattr(self, name).get_secret_value():
                    problems.append(f"MPESA_{name.upper()} is missing")
            if not self.express_shortcode:
                problems.append("MPESA_EXPRESS_SHORTCODE is missing")
            if problems:
                raise ValueError("; ".join(problems))
        return self


@lru_cache
def get_mpesa_settings() -> MpesaSettings:
    return MpesaSettings()
