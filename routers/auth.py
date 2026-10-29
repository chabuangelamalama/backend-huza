from fastapi import APIRouter, BackgroundTasks, Body, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from core.dependencies import get_auth_service, get_current_user, get_mailer
from models.user import User
from services.auth_service import AuthService
from services.email_service import EmailSender

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_REQUESTED = "If that email has an account, a reset link is on its way."


def user_dict(user: User) -> dict:
    """Return public user details without exposing sensitive fields."""
    data = {
        "id": str(user.user_id),
        "email": user.email,
        "role": user.user_role.value,
    }

    business = user.business
    if business is not None:
        data["business"] = {
            "approval_status": business.approval_status.value,
        }

    return data


@router.post("/login")
def login(
    body: dict = Body(...),
    service: AuthService = Depends(get_auth_service),
):
    token, expires_in, user = service.login(
        body.get("email"),
        body.get("password"),
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": user_dict(user),
    }


@router.post("/token", include_in_schema=False)
def login_form(
    form: OAuth2PasswordRequestForm = Depends(),
    service: AuthService = Depends(get_auth_service),
):
    """Form-based sign in for Swagger Authorize button."""
    token, expires_in, user = service.login(
        form.username,
        form.password,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": user_dict(user),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    """Return the current user's public details."""
    return user_dict(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    """Revoke tokens for this account."""
    service.logout(user)


@router.post("/change-password")
def change_password(
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    """Change the current user's password."""
    token, expires_in = service.change_password(
        user,
        body.get("current_password"),
        body.get("new_password"),
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": user_dict(user),
    }


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    background: BackgroundTasks,
    body: dict = Body(...),
    service: AuthService = Depends(get_auth_service),
    mailer: EmailSender = Depends(get_mailer),
):
    """Request a password-reset email."""
    message = service.prepare_password_reset(body.get("email"))

    if message is not None:
        background.add_task(mailer.send, message)

    return {"detail": RESET_REQUESTED}


@router.post("/reset-password")
def reset_password(
    body: dict = Body(...),
    service: AuthService = Depends(get_auth_service),
):
    """Reset a password using the reset code."""
    service.reset_password(
        body.get("email"),
        body.get("code"),
        body.get("password"),
    )
    return {"detail": "Password changed. Sign in with your new password."}
