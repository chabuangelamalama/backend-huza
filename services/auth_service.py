import math
import secrets
from datetime import datetime, timedelta, timezone

from core.config import Settings
from core.exceptions import (
    AccountLocked,
    InvalidCredentials,
    InvalidResetToken,
    WrongPassword,
)
from core.security import (
    burn_password_check,
    create_access_token,
    hash_password,
    verify_and_update,
)
from models.user import User
from repositories.user_repository import UserRepository
from services.email_service import OutgoingEmail, build_password_reset_email


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class AuthService:
    def __init__(self, users: UserRepository, settings: Settings) -> None:
        self.users = users
        self.settings = settings

    # ------------------------------------------------------------------ #
    # Sign in / out
    # ------------------------------------------------------------------ #

    def login(self, email: str, password: str) -> tuple[str, int, User]:
        """Returns (access_token, expires_in_seconds, user)."""
        user = self.users.get_by_email(normalize_email(email), for_update=True)
        if user is None:
            burn_password_check()
            raise InvalidCredentials()

        now = _now()
        self._ensure_not_locked(user, now)

        valid, upgraded_hash = verify_and_update(password, user.password_hash)
        if not valid:
            self._record_failed_attempt(user, now)
            raise InvalidCredentials()

        if upgraded_hash:
            user.password_hash = upgraded_hash
        user.failed_login_attempts = 0
        user.locked_until = None
        self.users.commit()

        token, expires_in = self._issue_token(user)
        return token, expires_in, user

    def logout(self, user: User) -> None:
        """Revokes every token this user has, on every device."""
        user.token_version = (user.token_version or 0) + 1
        self.users.commit()

    # ------------------------------------------------------------------ #
    # Passwords
    # ------------------------------------------------------------------ #

    def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> tuple[str, int]:
        """Returns a fresh (access_token, expires_in); older tokens stop working."""
        now = _now()
        self._ensure_not_locked(user, now)

        valid, _ = verify_and_update(current_password, user.password_hash)
        if not valid:
            self._record_failed_attempt(user, now)
            raise WrongPassword()

        user.password_hash = hash_password(new_password)
        user.token_version = (user.token_version or 0) + 1
        user.failed_login_attempts = 0
        user.locked_until = None
        self.users.commit()
        self.users.refresh(user)
        return self._issue_token(user)

    def prepare_password_reset(self, email: str) -> OutgoingEmail | None:
        """Generates a 6-digit OTP, stores its hash, and returns the email."""
        user = self.users.get_by_email(normalize_email(email), for_update=True)
        if user is None:
            return None

        # Generate a random 6-digit code
        code = f"{secrets.randbelow(1_000_000):06d}"

        # Save hash and 15-minute expiration
        user.reset_code_hash = hash_password(code)
        user.reset_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        self.users.commit()

        return build_password_reset_email(user, code, self.settings)

    def reset_password(self, email: str, code: str, new_password: str) -> None:
        """Verifies the 6-digit OTP code and updates the password."""
        user = self.users.get_by_email(normalize_email(email), for_update=True)
        if user is None:
            raise InvalidResetToken()

        if not user.reset_code_hash or not user.reset_code_expires_at:
            raise InvalidResetToken()

        now = _now()
        code_expires_at = _aware(user.reset_code_expires_at)
        if code_expires_at is None or now > code_expires_at:
            user.reset_code_hash = None
            user.reset_code_expires_at = None
            self.users.commit()
            raise InvalidResetToken()

        valid, _ = verify_and_update(code.strip(), user.reset_code_hash)
        if not valid:
            raise InvalidResetToken()

        user.password_hash = hash_password(new_password)
        user.token_version = (user.token_version or 0) + 1
        user.failed_login_attempts = 0
        user.locked_until = None
        user.reset_code_hash = None
        user.reset_code_expires_at = None
        self.users.commit()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _issue_token(self, user: User) -> tuple[str, int]:
        return create_access_token(
            user.user_id, str(user.user_role), user.token_version or 0, self.settings
        )

    def _ensure_not_locked(self, user: User, now: datetime) -> None:
        locked_until = _aware(user.locked_until)
        if locked_until is not None and locked_until > now:
            raise AccountLocked(math.ceil((locked_until - now).total_seconds()))

    def _record_failed_attempt(self, user: User, now: datetime) -> None:
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= self.settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=self.settings.lockout_minutes)
            user.failed_login_attempts = 0
        self.users.commit()
