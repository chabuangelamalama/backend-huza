from fastapi import HTTPException, status


def get_current_user():
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign-in is not set up yet.",
    )
