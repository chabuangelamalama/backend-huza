import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import Settings, get_settings
from models.enums import UserRole

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    role: UserRole


def create_access_token(
    user_id: uuid.UUID,
    role: UserRole,
    settings: Settings | None = None,
    expires_minutes: int = 60,
) -> str:
    settings = settings or get_settings()
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if credentials is None:
        raise unauthorized("Log in to continue")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return CurrentUser(
            user_id=uuid.UUID(payload["sub"]), role=UserRole(payload["role"])
        )
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized("Your login is not valid") from None


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can do this",
        )
    return user
