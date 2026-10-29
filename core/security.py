import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import Settings, get_settings
from models.user import UserRole

ACCESS = "access"
RESET = "reset"
VERIFY = "verify"

_hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)


class TokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenPayload:
    user_id: uuid.UUID
    token_version: int | None = None
    role: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    role: UserRole


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_and_update(password: str, password_hash: str) -> tuple[bool, str | None]:
    try:
        _hasher.verify(password_hash, password)
        needs_rehash = _hasher.check_needs_rehash(password_hash)
        new_hash = _hasher.hash(password) if needs_rehash else None
        return True, new_hash
    except Exception:
        return False, None


def burn_password_check() -> None:
    fake_hash = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$RdescudvJCsgqlfreuzflGnhZw7+47WLPAYfmGs2361"
    try:
        _hasher.verify(fake_hash, "wrong-password")
    except Exception:
        pass


def _encode(
    payload: dict, token_type: str, minutes: int, settings: Settings
) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=minutes)
    data = {
        **payload,
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(data, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, minutes * 60


class TokenResult(str):
    """String subclass that also allows tuple unpacking (token, exp_seconds)."""
    def __new__(cls, token: str, exp_seconds: int):
        obj = super().__new__(cls, token)
        obj.token = token
        obj.exp_seconds = exp_seconds
        return obj

    def __iter__(self):
        yield str(self)
        yield self.exp_seconds

    def __getitem__(self, index):
        if index == 0:
            return str(self)
        elif index == 1:
            return self.exp_seconds
        raise IndexError("TokenResult index out of range")

    def __len__(self):
        return 2


def create_access_token(
    user_id: uuid.UUID,
    role: str | UserRole,
    token_version: int = 1,
    settings: Settings | None = None,
    expires_minutes: int | None = None,
):
    cfg = settings or get_settings()
    role_str = role.value if isinstance(role, UserRole) else str(role)
    mins = expires_minutes if expires_minutes is not None else cfg.access_token_minutes
    token, exp_seconds = _encode(
        {"sub": str(user_id), "role": role_str, "tv": token_version},
        ACCESS,
        mins,
        cfg,
    )
    return TokenResult(token, exp_seconds)


def create_reset_token(
    user_id: uuid.UUID, token_version: int, settings: Settings
) -> str:
    token, _ = _encode(
        {"sub": str(user_id), "tv": token_version},
        RESET,
        settings.reset_token_minutes,
        settings,
    )
    return token


def create_verify_token(user_id: uuid.UUID, email: str, settings: Settings) -> str:
    token, _ = _encode(
        {"sub": str(user_id), "email": email.lower().strip()},
        VERIFY,
        settings.verify_token_minutes,
        settings,
    )
    return token


def decode_token(token: str, expected_type: str, settings: Settings) -> TokenPayload:
    try:
        data = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
        if data.get("typ") and data.get("typ") != expected_type:
            raise TokenError("wrong token type")
        tv = data.get("tv")
        return TokenPayload(
            user_id=uuid.UUID(data["sub"]),
            token_version=int(tv) if tv is not None else None,
            role=data.get("role"),
            email=data.get("email"),
        )
    except TokenError:
        raise
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise TokenError(str(exc)) from exc


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
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        role_val = payload.get("role")
        user_role = UserRole(role_val) if role_val in [r.value for r in UserRole] else UserRole[role_val]
        return CurrentUser(
            user_id=uuid.UUID(payload["sub"]), role=user_role
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
