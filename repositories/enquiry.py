import uuid
from typing import Any, Optional, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.enquiry import Enquiry


class EnquiryRepository:
    def __init__(self) -> None:
        self.model = Enquiry
        self._immutable_fields = {"enquiry_id", "created_at", "updated_at"}

    def get(self, db: Session, enquiry_id: uuid.UUID) -> Optional[Enquiry]:
        """Retrieves a single enquiry by its primary tracking ID."""
        return db.get(self.model, enquiry_id)

    def get_all(self, db: Session, skip: int = 0, limit: int = 100):
        """Lists all enquiries globally with standard pagination support."""
        statement = select(self.model).offset(skip).limit(limit)
        return db.scalars(statement).all()

    def create(self, db: Session, data: Dict[str, Any], commit: bool = True) -> Enquiry:
        """Persists a brand new enquiry payload directly into the database row engine."""
        enquiry = self.model(**data)
        db.add(enquiry)
        if commit:
            db.commit()
            db.refresh(enquiry)
        else:
            db.flush()
        return enquiry

    def update(self, db: Session, db_obj: Enquiry, data: Dict[str, Any], commit: bool = True) -> Enquiry:
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

    def delete(self, db: Session, db_obj: Enquiry, commit: bool = True) -> None:
        """Deletes a targeted enquiry log entirely from database tracking layers."""
        db.delete(db_obj)
        if commit:
            db.commit()
        else:
            db.flush()


enquiry_repository = EnquiryRepository()