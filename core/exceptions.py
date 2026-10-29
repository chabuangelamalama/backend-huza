"""Errors that map straight to an HTTP response (see the handler in main.py)."""

import math


class AppError(Exception):
    status_code = 400
    detail = "Bad request."

    def __init__(
        self, detail: str | None = None, headers: dict[str, str] | None = None
    ) -> None:
        self.detail = detail or self.detail
        self.headers = headers
        super().__init__(self.detail)


class InvalidCredentials(AppError):
    """Same message for a wrong email and a wrong password."""

    status_code = 401
    detail = "Email or password is incorrect."

    def __init__(self) -> None:
        super().__init__(headers={"WWW-Authenticate": "Bearer"})


class AccountLocked(AppError):
    status_code = 429

    def __init__(self, retry_after_seconds: int) -> None:
        minutes = max(1, math.ceil(retry_after_seconds / 60))
        super().__init__(
            f"Too many failed attempts. Try again in {minutes} minute(s).",
            headers={"Retry-After": str(retry_after_seconds)},
        )


class InvalidToken(AppError):
    status_code = 401
    detail = "Not authenticated."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail, headers={"WWW-Authenticate": "Bearer"})


class InvalidResetToken(AppError):
    status_code = 400
    detail = "This reset link is invalid or has expired."


class WrongPassword(AppError):
    status_code = 400
    detail = "Current password is incorrect."


class PermissionDenied(AppError):
    status_code = 403
    detail = "You do not have permission to do this."


class NotFound(AppError):
    status_code = 404
    detail = "Not found."
