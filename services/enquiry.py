import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.security import CurrentUser
from models.business import ApprovalStatus
from models.enquiry import EnquiryStatus
from models.listing import ListingStatus
from repositories.enquiry import enquiry_repository
from schemas.enquiry import EnquiryCreate


def _role_of(current_user: CurrentUser) -> str:
    role = current_user.role
    return str(getattr(role, "value", role)).upper()


def _authorise(current_user: CurrentUser, action: str) -> None:
    role = _role_of(current_user)
    if role not in {"ADMIN", "BUSINESS_USER"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: a {role.lower()} cannot {action}.",
        )


class EnquiryService:
    def _get_enquiry_or_404(self, db: Session, enquiry_id: uuid.UUID):
        enquiry = enquiry_repository.get(db, enquiry_id)
        if not enquiry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Enquiry not found.",
            )
        return enquiry

    def _business_of(
        self,
        db: Session,
        current_user: CurrentUser,
        action: str,
        require_approved: bool = False,
    ):
        if _role_of(current_user) != "BUSINESS_USER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: only business accounts can {action}.",
            )

        user = enquiry_repository.get_user(db, current_user.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your login is not valid.",
            )
        if user.business_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: only business accounts can {action}.",
            )

        business = enquiry_repository.get_business(db, user.business_id)
        if business is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: only business accounts can {action}.",
            )
        if require_approved and business.approval_status != ApprovalStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Access denied: your business is not approved, "
                    f"so you cannot {action}."
                ),
            )
        return business

    def _is_participant(self, enquiry, business_id: uuid.UUID) -> bool:
        return business_id in {
            enquiry.buyer_business_id,
            enquiry.seller_business_id,
        }

    def create_enquiry(
        self,
        db: Session,
        payload: EnquiryCreate,
        current_user: CurrentUser,
    ):
        _authorise(current_user, "create enquiries")
        business = self._business_of(
            db,
            current_user,
            "create enquiries",
            require_approved=True,
        )

        if payload.buyer_business_id != business.business_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only create enquiries for your own business.",
            )

        listing = enquiry_repository.get_listing(db, payload.listing_id)
        if listing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Listing not found.",
            )
        if payload.seller_business_id != listing.business_id:
            raise HTTPException(
                status_code=422,
                detail="The seller does not own this listing.",
            )
        if payload.buyer_business_id == payload.seller_business_id:
            raise HTTPException(
                status_code=422,
                detail="A business cannot enquire about its own listing.",
            )
        if listing.status != ListingStatus.PUBLISHED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This listing is not available for enquiries.",
            )

        total_amount = payload.quantity * payload.unit_price
        if total_amount != total_amount.to_integral_value():
            # M-Pesa only collects whole shillings, so a fractional total could
            # be agreed but never paid.
            raise HTTPException(
                status_code=422,
                detail=(
                    f"The total ({total_amount.normalize():f} KES) must be a whole "
                    "number of shillings. Adjust the quantity or unit price."
                ),
            )

        if enquiry_repository.find_open(
            db, payload.listing_id, payload.buyer_business_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An open enquiry for this listing already exists.",
            )

        data = payload.model_dump()
        data["total_amount"] = total_amount
        data["status"] = EnquiryStatus.ENQUIRY

        try:
            return enquiry_repository.create(db, data)
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An open enquiry for this listing already exists.",
            ) from None

    def list_enquiries(
        self,
        db: Session,
        current_user: CurrentUser,
        **filters,
    ):
        _authorise(current_user, "view enquiries")

        business_id = None
        if _role_of(current_user) != "ADMIN":
            business = self._business_of(db, current_user, "view enquiries")
            business_id = business.business_id

        return enquiry_repository.search(db, business_id=business_id, **filters)

    def get_enquiry(
        self,
        db: Session,
        enquiry_id: uuid.UUID,
        current_user: CurrentUser,
    ):
        _authorise(current_user, "view enquiries")
        enquiry = self._get_enquiry_or_404(db, enquiry_id)

        if _role_of(current_user) != "ADMIN":
            business = self._business_of(db, current_user, "view enquiries")
            if not self._is_participant(enquiry, business.business_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Enquiry not found.",
                )

        return enquiry

    def accept_enquiry(
        self,
        db: Session,
        enquiry_id: uuid.UUID,
        current_user: CurrentUser,
    ):
        """Seller agrees to the enquiry, which makes it payable by the buyer."""
        _authorise(current_user, "accept enquiries")
        business = self._business_of(
            db,
            current_user,
            "accept enquiries",
            require_approved=True,
        )
        enquiry = enquiry_repository.get(db, enquiry_id, lock=True)
        if enquiry is None or not self._is_participant(enquiry, business.business_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Enquiry not found.",
            )
        if enquiry.seller_business_id != business.business_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the seller can accept this enquiry.",
            )
        if enquiry.status != EnquiryStatus.ENQUIRY:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This enquiry is already {enquiry.status.value.lower()}.",
            )

        listing = enquiry_repository.get_listing(db, enquiry.listing_id)
        if listing is None or listing.quantity < enquiry.quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The listing no longer has enough stock.",
            )

        now = datetime.now(timezone.utc)
        return enquiry_repository.update(
            db,
            enquiry,
            {
                "status": EnquiryStatus.AGREED,
                "accepted_at": now,
                "first_response_at": enquiry.first_response_at or now,
            },
        )

    def open_enquiry(self, db: Session, enquiry_id: uuid.UUID):
        enquiry = self._get_enquiry_or_404(db, enquiry_id)
        return enquiry_repository.update(db, enquiry, {"status": EnquiryStatus.ENQUIRY})


enquiry_service = EnquiryService()
