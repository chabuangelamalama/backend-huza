import uuid

from core.exceptions import NotFound
from models.user import User, UserRole
from repositories.user_repository import UserRepository


class UserService:
    """Administrator operations on user accounts."""

    def __init__(self, users: UserRepository) -> None:
        self.users = users

    def list_users(
        self, *, role: UserRole | None, limit: int, offset: int
    ) -> tuple[list[User], int]:
        return self.users.list_users(role=role, limit=limit, offset=offset)

    def unlock(self, user_id: uuid.UUID) -> User:
        user = self.users.get_by_id(user_id, for_update=True)
        if user is None:
            raise NotFound("User not found.")
        user.failed_login_attempts = 0
        user.locked_until = None
        self.users.commit()
        return user
