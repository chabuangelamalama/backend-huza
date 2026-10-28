from uuid import UUID

from sqlalchemy.orm import Session

from models.business import Business
from models.listing import Listing, ListingStatus, ListingType, Stream
from models.location import Location


class ListingRepository:
    def get(self, db: Session, listing_id: UUID) -> Listing | None:
        return db.get(Listing, listing_id)

    def get_business(self, db: Session, business_id: UUID) -> Business | None:
        return db.get(Business, business_id)

    def get_location(self, db: Session, location_id: UUID) -> Location | None:
        return db.get(Location, location_id)

    def get_all(
        self,
        db: Session,
        status: ListingStatus | None = None,
        stream: Stream | None = None,
        listing_type: ListingType | None = None,
        location_id: UUID | None = None,
        search: str | None = None,
    ) -> list[Listing]:
        query = db.query(Listing)
        if status:
            query = query.filter(Listing.status == status)
        if stream:
            query = query.filter(Listing.stream == stream)
        if listing_type:
            query = query.filter(Listing.listing_type == listing_type)
        if location_id:
            query = query.filter(Listing.location_id == location_id)
        if search:
            query = query.filter(Listing.material_or_product.ilike(f"%{search}%"))
        return query.order_by(Listing.created_at.desc()).all()

    def get_by_business(self, db: Session, business_id: UUID) -> list[Listing]:
        return (
            db.query(Listing)
            .filter(Listing.business_id == business_id)
            .order_by(Listing.created_at.desc())
            .all()
        )

    def create(self, db: Session, data: dict) -> Listing:
        return self._save(db, Listing(**data))

    def update(self, db: Session, listing: Listing, data: dict) -> Listing:
        for key, value in data.items():
            setattr(listing, key, value)
        return self._save(db, listing)

    def _save(self, db: Session, record):
        db.add(record)
        db.commit()
        db.refresh(record)
        return record


listing_repository = ListingRepository()
