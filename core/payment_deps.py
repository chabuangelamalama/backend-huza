"""FastAPI dependencies used by the payment router."""

from functools import lru_cache
from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session

from core.payment_config import MomoSettings, get_momo_settings
from database import get_db
from models import User

from services.momo import MomoClient, MomoGateway


@lru_cache
def _momo_client() -> MomoGateway:
    settings = get_momo_settings()

    return MomoClient(settings)


def get_momo_client() -> MomoGateway:
    return _momo_client()


def get_settings() -> MomoSettings:
    return get_momo_settings()


def get_current_user(db: Session = Depends(get_db)) -> User:

    real_user = db.query(User).first()

    if not real_user:
        raise HTTPException(
            status_code=404,
            detail="No users found in your database app_user table. Please register a user first.",
        )

    return real_user
