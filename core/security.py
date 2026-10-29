import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from core.config import Settings

ACCESS = "access"
RESET = "reset"
VERIFY = "verify"

_hasher = PasswordHasher()


class TokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenPayload:
    user_id: uuid.UUID
    token_version: int | None = None
    role: str | None = None
    email: str | None = None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_and_update(password: str, password_hash: str) -> tuple[bool, str | None]:
    try:
        needs_rehash = _hasher.check_needs_rehash(password_hash)
        _hasher.verify(password_hash, password)
        new_hash = _hasher.hash(password) if needs_rehash else None
        return True, new_hash
    except VerifyMismatchError:
        return False, None


def burn_password_check() -> None:
    fake_hash = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$RdescudvJCsgqlfreuzflGnhZw7+47WLPAYfmGs2361"
    try:
        _hasher.verify(fake_hash, "wrong-password")
    except Exception:
        pass


def _encode(payload: dict, token_type: str, minutes: int, settings: Settings) -> tuple[str, int]:
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


def create_access_token(
    user_id: uuid.UUID, role: str, token_version: int, settings: Settings
) -> tuple[str, int]:
    return _encode(
        {"sub": str(user_id), "role": role, "tv": token_version},
        ACCESS,
        settings.access_token_minutes,
        settings,
    )


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


def create_verify_token(
    user_id: uuid.UUID, email: str, settings: Settings
) -> str:
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
        if data.get("typ") != expected_type:
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
