from fastapi import APIRouter, BackgroundTasks, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from core.dependencies import get_auth_service, get_current_user, get_mailer
from models.user import User
from schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
)
from services.auth_service import AuthService
from services.email_service import EmailSender

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_REQUESTED = "If that email has an account, a reset link is on its way."


def _format_user(user: User) -> dict:
    role_str = user.user_role.value if hasattr(user.user_role, "value") else str(user.user_role)
    biz = getattr(user, "business", None)
    biz_dict = None
    if biz is not None:
        status_val = getattr(biz, "approval_status", None)
        biz_dict = {
            "business_id": str(getattr(biz, "business_id", "")),
            "approval_status": status_val.value if hasattr(status_val, "value") else str(status_val or "PENDING"),
        }
    return {
        "user_id": str(user.user_id),
        "business_id": str(user.business_id) if user.business_id else None,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "role": role_str,
        "user_role": role_str,
        "business": biz_dict,
    }


@router.post("/login")
def login(body: LoginRequest, service: AuthService = Depends(get_auth_service)):
    """Sign in with email and password."""
    token, expires_in, user = service.login(body.email, body.password)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": _format_user(user),
    }


@router.post("/token", include_in_schema=False)
def login_form(
    form: OAuth2PasswordRequestForm = Depends(),
    service: AuthService = Depends(get_auth_service),
):
    """Form-based sign in for Swagger Authorize button."""
    token, expires_in, user = service.login(form.username, form.password)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": _format_user(user),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _format_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    """Revokes tokens for this account."""
    service.logout(user)


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    token, expires_in = service.change_password(
        user, body.current_password, body.new_password
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": _format_user(user),
    }


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    body: ForgotPasswordRequest,
    background: BackgroundTasks,
    service: AuthService = Depends(get_auth_service),
    mailer: EmailSender = Depends(get_mailer),
):
    message = service.prepare_password_reset(body.email)
    if message is not None:
        background.add_task(mailer.send, message)
    return {"detail": RESET_REQUESTED}


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service),
):
    service.reset_password(body.email, body.code, body.password)
    return {"detail": "Password changed. Sign in with your new password."}
