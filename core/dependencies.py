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
from services.email_service import EmailSender, LoggingEmailSender, SmtpEmailSender
from services.registration_service import RegistrationService
from services.user_service import UserService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_auth_service(
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(users, settings)


def get_registration_service(
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> RegistrationService:
    return RegistrationService(users, settings)


def get_user_service(
    users: UserRepository = Depends(get_user_repository),
) -> UserService:
    return UserService(users)


def get_mailer(settings: Settings = Depends(get_settings)) -> EmailSender:
    if settings.smtp_host:
        return SmtpEmailSender(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            starttls=settings.smtp_starttls,
            sender=settings.email_from,
        )
    return LoggingEmailSender(reveal_links=not settings.is_production)


# --------------------------------------------------------------------------- #
# Authentication and role-based access
# --------------------------------------------------------------------------- #


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> User:
    # Missing token, or called directly without FastAPI resolving dependencies.
    if (
        not token
        or isinstance(token, DependsClass)
        or isinstance(settings, DependsClass)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_token(token, ACCESS, settings)
    except TokenError:
        raise InvalidToken("Invalid or expired token.") from None

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
