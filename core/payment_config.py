from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MomoSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOMO_", env_file=".env", extra="ignore"
    )

    environment: Literal["sandbox", "production"] = "sandbox"

    mode: Literal["live", "simulated"] = "live"
    simulator_delay_seconds: float = 5.0
    base_url: str = "https://sandbox.momodeveloper.mtn.com"

    target_environment: str = "sandbox"

    currency: str = "EUR"

    collection_subscription_key: SecretStr = SecretStr("")
    collection_api_user: str = ""
    collection_api_key: SecretStr = SecretStr("")
    disbursement_subscription_key: SecretStr = SecretStr("")
    disbursement_api_user: str = ""
    disbursement_api_key: SecretStr = SecretStr("")

    callback_base_url: str = ""

    callback_secret: SecretStr = SecretStr("")

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
    def _validate(self) -> "MomoSettings":
        if self.environment == "production":
            problems = []
            if self.mode != "live":
                problems.append("MOMO_MODE must be live in production")
            if not self.base_url.startswith("https://"):
                problems.append("MOMO_BASE_URL must be https")
            if self.currency != "RWF":
                problems.append("MOMO_CURRENCY must be RWF in production")
            if not self.callback_base_url.startswith("https://"):
                problems.append("MOMO_CALLBACK_BASE_URL must be https")
            if len(self.callback_secret.get_secret_value()) < 32:
                problems.append("MOMO_CALLBACK_SECRET must be at least 32 chars")
            for name in (
                "collection_subscription_key",
                "collection_api_key",
                "disbursement_subscription_key",
                "disbursement_api_key",
            ):
                if not getattr(self, name).get_secret_value():
                    problems.append(f"MOMO_{name.upper()} is missing")
            for name in ("collection_api_user", "disbursement_api_user"):
                if not getattr(self, name):
                    problems.append(f"MOMO_{name.upper()} is missing")
            if problems:
                raise ValueError("; ".join(problems))
        return self


@lru_cache
def get_momo_settings() -> MomoSettings:
    return MomoSettings()
