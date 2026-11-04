"""FastAPI dependencies: current user, role checks, and service wiring."""

from fastapi import Depends, HTTPException, status
from fastapi.params import Depends as DependsClass
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from database import get_db
from core.exceptions import InvalidToken, PermissionDenied
from core.security import ACCESS, TokenError, decode_token
from models.user import User, UserRole
from repositories.user_repository import UserRepository
from services.auth_service import AuthService
from services.email_service import EmailSender, build_email_sender
from services.registration_service import RegistrationService
from services.user_service import UserService


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_auth_service(
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(users, settings)


def get_user_service(
    users: UserRepository = Depends(get_user_repository),
) -> UserService:
    return UserService(users)


def get_mailer(settings: Settings = Depends(get_settings)) -> EmailSender:
    return build_email_sender(settings)


# --------------------------------------------------------------------------- #
# Authentication and role-based access
# --------------------------------------------------------------------------- #


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> User:
    # Direct function calls in unit tests (bypassing FastAPI resolution)
    if isinstance(token, DependsClass) or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if isinstance(settings, DependsClass):
        settings = get_settings()

    try:
        claims = decode_token(token, ACCESS, settings)
    except TokenError:
        raise InvalidToken("Invalid or expired token.") from None

    if isinstance(users, DependsClass):
        db = next(get_db())
        users = UserRepository(db)

    user = users.get_by_id(claims.user_id)

    if user is None or user.token_version != claims.token_version:
        raise InvalidToken("Invalid or expired token.")

    return user


def require_roles(*roles: UserRole):
    """Dependency factory: allow only users holding one of the given roles."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.user_role not in roles:
            raise PermissionDenied()
        return user

    return checker


require_admin = require_roles(UserRole.ADMIN)
require_business_user = require_roles(UserRole.BUSINESS_USER)


def get_registration_service(
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> RegistrationService:
    return RegistrationService(users, settings)
