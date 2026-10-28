import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.security import CurrentUser, get_current_user
from database import get_db
from schemas.notification import (
    NotificationCreate,
    NotificationFilter,
    NotificationRead,
    UnreadCount,
    UpdatedCount,
)
from services.notification import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    filters: Annotated[NotificationFilter, Query()],
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return notification_service.list_notifications(
        db, current_user, **filters.model_dump()
    )


@router.get("/unread-count", response_model=UnreadCount)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    count = notification_service.unread_count(db, current_user)
    return UnreadCount(count=count)


@router.post("/read-all", response_model=UpdatedCount)
def read_all_notifications(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    updated = notification_service.mark_all_read(db, current_user)
    return UpdatedCount(updated=updated)


@router.get("/{notification_id}", response_model=NotificationRead)
def get_notification(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return notification_service.get_notification(db, notification_id, current_user)


@router.post("", response_model=NotificationRead)
def create_notification(
    data: NotificationCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return notification_service.create_notification(db, data, current_user)


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def read_notification(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return notification_service.mark_read(db, notification_id, current_user)


@router.delete("/{notification_id}")
def delete_notification(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    notification_service.delete_notification(db, notification_id, current_user)
