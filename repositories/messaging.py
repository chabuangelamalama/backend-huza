import uuid
from typing import Any, Sequence, Optional, Dict
from sqlalchemy import select
from sqlalchemy.orm import Session
from models.message import Message


class MessageRepository:
    def __init__(self) -> None:
        self.model = Message
        self._immutable_fields = {"message_id", "created_at", "updated_at"}

    def get(self, db: Session, message_id: uuid.UUID) -> Optional[Message]:
        """Retrieves a single message by its primary tracking ID."""
        return db.get(self.model, message_id)

    def get_all(self, db: Session, skip: int = 0, limit: int = 100) -> Sequence[Message]:
        """Lists all messages globally with standard pagination support."""
        statement = select(self.model).offset(skip).limit(limit)
        return db.scalars(statement).all()

    def get_by_enquiry(self, db: Session, enquiry_id: uuid.UUID) -> Sequence[Message]:
        """Fetches all messages belonging to a specific conversation pipeline ordered by time."""
        statement = (
            select(self.model)
            .where(self.model.enquiry_id == enquiry_id)
            .order_by(self.model.created_at.asc())
        )
        return db.scalars(statement).all()

    def create(self, db: Session, data: Dict[str, Any], commit: bool = True) -> Message:
        """Persists a brand new message payload directly into the database row engine."""
        message = self.model(**data)
        db.add(message)
        if commit:
            db.commit()
            db.refresh(message)
        else:
            db.flush()  
        return message

    def update(self, db: Session, db_obj: Message, data: Dict[str, Any], commit: bool = True) -> Message:
        """Modifies permitted fields safely against active database rows."""
        allowed_columns = self.model.__table__.columns.keys()
        
        for field, value in data.items():
            if field in allowed_columns and field not in self._immutable_fields:
                setattr(db_obj, field, value)
                
        if commit:
            db.commit()
            db.refresh(db_obj)
        else:
            db.flush()
        return db_obj

    def delete(self, db: Session, db_obj: Message, commit: bool = True) -> None:
        """Deletes a targeted message log entirely from database tracking layers."""
        db.delete(db_obj)
        if commit:
            db.commit()
        else:
            db.flush()


message_repository = MessageRepository()
