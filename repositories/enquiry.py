import uuid
from typing import Any, Dict, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models.business import Business
from models.enquiry import Enquiry, EnquiryStatus
from models.listing import Listing
from models.user import User

OPEN_STATUSES = (
    EnquiryStatus.ENQUIRY,
    EnquiryStatus.AGREED,
    EnquiryStatus.PAID,
)


class EnquiryRepository:
    def __init__(self) -> None:
        self.model = Enquiry
        self._immutable_fields = {"enquiry_id", "created_at", "updated_at"}

    def get(
        self, db: Session, enquiry_id: uuid.UUID, lock: bool = False
    ) -> Optional[Enquiry]:
        return db.get(self.model, enquiry_id, with_for_update=lock)

    def get_user(self, db: Session, user_id: uuid.UUID) -> Optional[User]:
        return db.get(User, user_id)

    def get_business(self, db: Session, business_id: uuid.UUID) -> Optional[Business]:
        return db.get(Business, business_id)

    def get_listing(self, db: Session, listing_id: uuid.UUID) -> Optional[Listing]:
        return db.get(Listing, listing_id)

    def search(
        self,
        db: Session,
        *,
        business_id: Optional[uuid.UUID] = None,
        status: Optional[EnquiryStatus] = None,
        listing_id: Optional[uuid.UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ):
        query = select(self.model)
        if business_id is not None:
            query = query.where(
                or_(
                    self.model.buyer_business_id == business_id,
                    self.model.seller_business_id == business_id,
                )
            )
        if status is not None:
            query = query.where(self.model.status == status)
        if listing_id is not None:
            query = query.where(self.model.listing_id == listing_id)
        query = (
            query.order_by(self.model.created_at.desc(), self.model.enquiry_id)
            .limit(limit)
            .offset(offset)
        )
        return list(db.scalars(query))

    def get_all(self, db: Session, skip: int = 0, limit: int = 100):
        return self.search(db, limit=limit, offset=skip)

    def find_open(
        self,
        db: Session,
        listing_id: uuid.UUID,
        buyer_business_id: uuid.UUID,
    ) -> Optional[Enquiry]:
        query = select(self.model).where(
            self.model.listing_id == listing_id,
            self.model.buyer_business_id == buyer_business_id,
            self.model.status.in_(OPEN_STATUSES),
        )
        return db.scalars(query).first()

    def create(self, db: Session, data: Dict[str, Any], commit: bool = True) -> Enquiry:
        enquiry = self.model(**data)
        db.add(enquiry)
        if commit:
            db.commit()
            db.refresh(enquiry)
        else:
            db.flush()
        return enquiry

    def update(
        self, db: Session, db_obj: Enquiry, data: Dict[str, Any], commit: bool = True
    ) -> Enquiry:
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
        db.delete(db_obj)
        if commit:
            db.commit()
        else:
            db.flush()


enquiry_repository = EnquiryRepository()
