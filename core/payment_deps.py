"""FastAPI dependencies used by the payment router."""

from functools import lru_cache
from core.dependencies import get_current_user, get_db

from core.payment_config import MpesaSettings, get_mpesa_settings

from services.mpesa import MpesaClient, MpesaGateway

__all__ = ["get_current_user", "get_db", "get_mpesa_client", "get_settings"]


@lru_cache
def _mpesa_client() -> MpesaGateway:
    settings = get_mpesa_settings()
    return MpesaClient(settings)


def get_mpesa_client() -> MpesaGateway:
    return _mpesa_client()


def get_settings() -> MpesaSettings:
    return get_mpesa_settings()
