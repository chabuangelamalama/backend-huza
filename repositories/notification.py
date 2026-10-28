import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from models.notification import Notification

logger = logging.getLogger("repositories")


class NotificationRepository:
    def __init__(self):
        self.model = Notification

    def get(self, db: Session, notification_id: uuid.UUID):
        return db.get(self.model, notification_id)

    def search(
        self,
        db: Session,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        event_type=None,
        limit: int = 50,
        offset: int = 0,
    ):
        query = select(self.model).where(self.model.user_id == user_id)
        if unread_only:
            query = query.where(self.model.read_at.is_(None))
        if event_type is not None:
            query = query.where(self.model.event_type == event_type)
        query = (
            query.order_by(self.model.created_at.desc(), self.model.notification_id)
            .limit(limit)
            .offset(offset)
        )
        return list(db.scalars(query))

    def count_unread(self, db: Session, user_id: uuid.UUID) -> int:
        query = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.user_id == user_id, self.model.read_at.is_(None))
        )
        return db.scalar(query) or 0

    def create(self, db: Session, data: dict):
        try:
            db_obj = self.model(**data)
            db.add(db_obj)
            db.commit()
            db.refresh(db_obj)
            return db_obj
        except SQLAlchemyError as error:
            logger.error("Could not create notification: %s", error)
            db.rollback()
            raise

    def mark_read(self, db: Session, db_obj):
        if db_obj.read_at is not None:
            return db_obj
        try:
            db_obj.read_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(db_obj)
            return db_obj
        except SQLAlchemyError as error:
            logger.error("Could not mark notification as read: %s", error)
            db.rollback()
            raise

    def mark_all_read(self, db: Session, user_id: uuid.UUID) -> int:
        try:
            result = db.execute(
                update(self.model)
                .where(self.model.user_id == user_id, self.model.read_at.is_(None))
                .values(read_at=datetime.now(timezone.utc))
            )
            db.commit()
            return result.rowcount
        except SQLAlchemyError as error:
            logger.error("Could not mark all notifications as read: %s", error)
            db.rollback()
            raise

    def delete(self, db: Session, db_obj):
        try:
            db.delete(db_obj)
            db.commit()
        except SQLAlchemyError as error:
            logger.error("Could not delete notification: %s", error)
            db.rollback()
            raise


notification_repository = NotificationRepository()
