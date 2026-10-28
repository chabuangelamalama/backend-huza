"""FastAPI dependencies used by the payment router."""

from functools import lru_cache
from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session

from core.payment_config import MpesaSettings, get_mpesa_settings
from database import get_db
from models import User

from services.mpesa import MpesaClient, MpesaGateway


@lru_cache
def _mpesa_client() -> MpesaGateway:
    settings = get_mpesa_settings()

    return MpesaClient(settings)


def get_mpesa_client() -> MpesaGateway:
    return _mpesa_client()


def get_settings() -> MpesaSettings:
    return get_mpesa_settings()


def get_current_user(db: Session = Depends(get_db)) -> User:

    real_user = db.query(User).first()

    if not real_user:
        raise HTTPException(
            status_code=404,
            detail="No users found in your database app_user table. Please register a user first.",
        )

    return real_user
