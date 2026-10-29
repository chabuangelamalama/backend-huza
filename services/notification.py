import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.security import CurrentUser
from repositories.notification import notification_repository
from schemas.notification import NotificationCreate


def _role_of(current_user: CurrentUser) -> str:
    role = current_user.role
    return str(getattr(role, "value", role)).upper()


def _authorise(
    current_user: CurrentUser, action: str, admin_only: bool = False
) -> None:
    role = _role_of(current_user)
    allowed_roles = {"ADMIN"} if admin_only else {"ADMIN", "BUSINESS_USER"}
    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: a {role.lower()} cannot {action}.",
        )


def _find_notification(
    db: Session, notification_id: uuid.UUID, current_user: CurrentUser
):
    notification = notification_repository.get(db, notification_id)
    if notification is None or notification.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )
    return notification


class NotificationService:
    def list_notifications(
        self, db: Session, current_user: CurrentUser, **filters: Any
    ):
        _authorise(current_user, "view notifications")
        return notification_repository.search(db, current_user.user_id, **filters)

    def unread_count(self, db: Session, current_user: CurrentUser) -> int:
        _authorise(current_user, "view notifications")
        return notification_repository.count_unread(db, current_user.user_id)

    def get_notification(
        self, db: Session, notification_id: uuid.UUID, current_user: CurrentUser
    ):
        _authorise(current_user, "view notifications")
        return _find_notification(db, notification_id, current_user)

    def create_notification(
        self, db: Session, data: NotificationCreate, current_user: CurrentUser
    ):
        _authorise(current_user, "create notifications", admin_only=True)
        return self.notify(db, **data.model_dump())

    def notify(
        self,
        db: Session,
        user_id: uuid.UUID,
        event_type,
        enquiry_id: uuid.UUID | None = None,
        listing_id: uuid.UUID | None = None,
    ):
        values = {
            "user_id": user_id,
            "event_type": event_type,
            "enquiry_id": enquiry_id,
            "listing_id": listing_id,
        }
        try:
            return notification_repository.create(db, values)
        except IntegrityError:
            raise HTTPException(
                status_code=422,
                detail="The user, enquiry or listing does not exist.",
            ) from None

    def mark_read(
        self, db: Session, notification_id: uuid.UUID, current_user: CurrentUser
    ):
        _authorise(current_user, "update notifications")
        notification = _find_notification(db, notification_id, current_user)
        return notification_repository.mark_read(db, notification)

    def mark_all_read(self, db: Session, current_user: CurrentUser) -> int:
        _authorise(current_user, "update notifications")
        return notification_repository.mark_all_read(db, current_user.user_id)

    def delete_notification(
        self, db: Session, notification_id: uuid.UUID, current_user: CurrentUser
    ):
        _authorise(current_user, "delete notifications")
        notification = _find_notification(db, notification_id, current_user)
        notification_repository.delete(db, notification)


notification_service = NotificationService()
