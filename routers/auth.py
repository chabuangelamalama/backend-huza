from fastapi import APIRouter, BackgroundTasks, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from core.dependencies import get_auth_service, get_current_user, get_mailer
from models.user import User
from schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from services.auth_service import AuthService
from services.email_service import EmailSender

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_REQUESTED = "If that email has an account, a reset link is on its way."


def _token_response(token: str, expires_in: int, user: User) -> TokenResponse:
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, service: AuthService = Depends(get_auth_service)):
    """Sign in with email and password. Used by the mobile app."""
    token, expires_in, user = service.login(body.email, body.password)
    return _token_response(token, expires_in, user)


@router.post("/token", response_model=TokenResponse, include_in_schema=False)
def login_form(
    form: OAuth2PasswordRequestForm = Depends(),
    service: AuthService = Depends(get_auth_service),
):
    """Form-based sign in that powers the Authorize button in /docs.
    The form's 'username' field is the email."""
    token, expires_in, user = service.login(form.username, form.password)
    return _token_response(token, expires_in, user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    """Revokes every token for this account, on every device."""
    service.logout(user)


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    """Other sessions are signed out. The response carries a fresh token so this
    device stays signed in."""
    token, expires_in = service.change_password(
        user, body.current_password, body.new_password
    )
    return _token_response(token, expires_in, user)


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def forgot_password(
    body: ForgotPasswordRequest,
    background: BackgroundTasks,
    service: AuthService = Depends(get_auth_service),
    mailer: EmailSender = Depends(get_mailer),
):
    """Always answers the same way, so it cannot be used to find out which
    emails have accounts. The email is sent after the response."""
    message = service.prepare_password_reset(body.email)
    if message is not None:
        background.add_task(mailer.send, message)
    return MessageResponse(detail=RESET_REQUESTED)


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    body: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service),
):
    """Choose a new password using the token from the emailed link (single use)."""
    service.reset_password(body.email, body.code, body.password)
    return MessageResponse(detail="Password changed. Sign in with your new password.")
