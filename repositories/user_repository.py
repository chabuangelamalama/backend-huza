import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from models.user import User, UserRole


class UserRepository:
    """All database access for users. No business rules live here."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: uuid.UUID, *, for_update: bool = False) -> User | None:
        stmt = (
            select(User)
            .where(User.user_id == user_id)
            .options(selectinload(User.business))
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_email(self, email: str, *, for_update: bool = False) -> User | None:
        """Emails are stored lowercase, so callers pass a normalised email."""
        stmt = (
            select(User).where(User.email == email).options(selectinload(User.business))
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.db.execute(stmt).scalar_one_or_none()

    def list_users(
        self, *, role: UserRole | None, limit: int, offset: int
    ) -> tuple[list[User], int]:
        filters = [User.user_role == role] if role is not None else []
        total = self.db.execute(
            select(func.count()).select_from(User).where(*filters)
        ).scalar_one()
        rows = (
            self.db.execute(
                select(User)
                .where(*filters)
                .options(selectinload(User.business))
                .order_by(User.created_at.desc(), User.user_id)
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        return list(rows), total

    def commit(self) -> None:
        self.db.commit()

    def refresh(self, user: User) -> None:
        self.db.refresh(user)
