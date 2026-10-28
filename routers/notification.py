import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import CurrentUser, get_current_user
from models.notification import NotificationEvent
from schemas.notification import (
    NotificationCreate,
    NotificationRead,
    UnreadCount,
    UpdatedCount,
)
from services.notification import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    unread_only: bool = False,
    event_type: NotificationEvent | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return notification_service.list_notifications(
        db,
        current_user,
        unread_only=unread_only,
        event_type=event_type,
        limit=limit,
        offset=offset,
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


@router.post("", response_model=NotificationRead, status_code=status.HTTP_201_CREATED)
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


@router.delete(
    "/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_notification(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    notification_service.delete_notification(db, notification_id, current_user)
