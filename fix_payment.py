#!/usr/bin/env python3
"""Fix the payment layer. Run from the repo root: python fix_payment.py

1. models/payment.py   - adds state-consistency CHECKs, unique momo_transaction_id,
                         singular index names (matches the singular table rename).
2. migrations/versions - new migration: renames drifted pk/fk/ck/index names left over
                         from the plural-table migration, backfills paid_at, adds the new rules.
3. tests/test_models.py - make_payment helper fills paid_at/paid_out_at for you and
                         new tests cover every new rule.
Safe to run twice.
"""
from pathlib import Path

ROOT = Path(__file__).parent

MODEL = '''from sqlalchemy import (
    Column,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .base import Base, StrEnum, TimestampMixin, pg_enum, timestamptz, uuid_pk


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESSFUL = "SUCCESSFUL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PayoutStatus(StrEnum):
    NOT_DUE = "NOT_DUE"
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"


payment_status_t = pg_enum(PaymentStatus, "payment_status")
payout_status_t = pg_enum(PayoutStatus, "payout_status")


class Payment(TimestampMixin, Base):
    __tablename__ = "payment"

    payment_id = uuid_pk()
    enquiry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("enquiry.enquiry_id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount = Column(Numeric(19, 4), nullable=False)
    payer_phone = Column(Text, nullable=False)
    reference_id = Column(String(100), nullable=False, unique=True)
    momo_transaction_id = Column(String(100), nullable=True)
    status = Column(
        payment_status_t,
        nullable=False,
        default=PaymentStatus.PENDING,
        server_default=text("'PENDING'"),
    )
    failure_reason = Column(Text, nullable=True)
    payout_status = Column(
        payout_status_t,
        nullable=False,
        default=PayoutStatus.NOT_DUE,
        server_default=text("'NOT_DUE'"),
    )
    payout_reference = Column(String(100), nullable=True)
    paid_at = timestamptz(nullable=True)
    paid_out_at = timestamptz(nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "char_length(btrim(payer_phone)) > 0", name="payer_phone_not_blank"
        ),
        CheckConstraint(
            "(status = 'SUCCESSFUL') = (paid_at IS NOT NULL)",
            name="paid_at_matches_status",
        ),
        CheckConstraint(
            "failure_reason IS NULL OR status IN ('FAILED', 'CANCELLED')",
            name="failure_reason_only_when_unpaid",
        ),
        CheckConstraint(
            "payout_status = 'NOT_DUE' OR status = 'SUCCESSFUL'",
            name="payout_needs_successful_payment",
        ),
        CheckConstraint(
            "(payout_status = 'PAID') = (paid_out_at IS NOT NULL)",
            name="paid_out_at_matches_payout_status",
        ),
        Index(
            "uq_payment_one_pending",
            "enquiry_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            "uq_payment_one_successful",
            "enquiry_id",
            unique=True,
            postgresql_where=text("status = 'SUCCESSFUL'"),
        ),
        Index(
            "uq_payment_momo_transaction_id",
            "momo_transaction_id",
            unique=True,
            postgresql_where=text("momo_transaction_id IS NOT NULL"),
        ),
        Index("ix_payment_enquiry_id", "enquiry_id"),
    )

    enquiry = relationship("Enquiry", back_populates="payments")
'''

MIGRATION = '''"""payment integrity: consistent names, state rules, unique momo id

Revision ID: 9a2f7_payment_integrity
Revises: 8c4e1
Create Date: 2026-11-03 12:00:00

"""

from typing import Sequence, Union

from alembic import op


revision: str = "9a2f7_payment_integrity"
down_revision: Union[str, Sequence[str], None] = "8c4e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_RENAMES = [
    ("pk_payments", "pk_payment"),
    ("ck_payments_amount_positive", "ck_payment_amount_positive"),
    ("fk_payments_enquiry_id_enquiries", "fk_payment_enquiry_id_enquiry"),
]
INDEX_RENAMES = [
    ("ix_payments_enquiry_id", "ix_payment_enquiry_id"),
    ("uq_payments_one_pending", "uq_payment_one_pending"),
    ("uq_payments_one_successful", "uq_payment_one_successful"),
]
CHECKS = {
    "ck_payment_payer_phone_not_blank": "char_length(btrim(payer_phone)) > 0",
    "ck_payment_paid_at_matches_status": "(status = 'SUCCESSFUL') = (paid_at IS NOT NULL)",
    "ck_payment_failure_reason_only_when_unpaid": "failure_reason IS NULL OR status IN ('FAILED', 'CANCELLED')",
    "ck_payment_payout_needs_successful_payment": "payout_status = 'NOT_DUE' OR status = 'SUCCESSFUL'",
    "ck_payment_paid_out_at_matches_payout_status": "(payout_status = 'PAID') = (paid_out_at IS NOT NULL)",
}


def upgrade() -> None:
    for old, new in CONSTRAINT_RENAMES:
        op.execute(f"ALTER TABLE payment RENAME CONSTRAINT {old} TO {new}")
    for old, new in INDEX_RENAMES:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")

    # Backfill existing rows so the new rules can be applied.
    op.execute(
        "UPDATE payment SET paid_at = COALESCE(paid_at, updated_at) "
        "WHERE status = 'SUCCESSFUL'"
    )
    op.execute("UPDATE payment SET paid_at = NULL WHERE status <> 'SUCCESSFUL'")
    op.execute(
        "UPDATE payment SET failure_reason = NULL "
        "WHERE status NOT IN ('FAILED', 'CANCELLED')"
    )
    op.execute(
        "UPDATE payment SET payout_status = 'NOT_DUE', paid_out_at = NULL "
        "WHERE status <> 'SUCCESSFUL'"
    )
    op.execute(
        "UPDATE payment SET paid_out_at = COALESCE(paid_out_at, updated_at) "
        "WHERE payout_status = 'PAID'"
    )
    op.execute("UPDATE payment SET paid_out_at = NULL WHERE payout_status <> 'PAID'")

    for name, expr in CHECKS.items():
        op.create_check_constraint(op.f(name), "payment", expr)
    op.create_index(
        "uq_payment_momo_transaction_id",
        "payment",
        ["momo_transaction_id"],
        unique=True,
        postgresql_where="momo_transaction_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_payment_momo_transaction_id", table_name="payment")
    for name in CHECKS:
        op.drop_constraint(op.f(name), "payment", type_="check")
    for old, new in INDEX_RENAMES:
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    for old, new in CONSTRAINT_RENAMES:
        op.execute(f"ALTER TABLE payment RENAME CONSTRAINT {new} TO {old}")
'''

OLD_HELPER = '''def make_payment(session, enquiry, **changes):
    values = dict(
        enquiry_id=enquiry.enquiry_id,
        amount=Decimal("5000"),
        payer_phone="0788000000",
        reference_id=uuid.uuid4().hex,
    )
    values.update(changes)
'''
NEW_HELPER = '''def make_payment(session, enquiry, **changes):
    values = dict(
        enquiry_id=enquiry.enquiry_id,
        amount=Decimal("5000"),
        payer_phone="0788000000",
        reference_id=uuid.uuid4().hex,
    )
    values.update(changes)
    now = datetime.now(timezone.utc)
    if values.get("status") == PaymentStatus.SUCCESSFUL:
        values.setdefault("paid_at", now)
    if values.get("payout_status") == PayoutStatus.PAID:
        values.setdefault("paid_out_at", now)
'''

NEW_TESTS = '''

# --- payment integrity rules ---
def test_payment_phone_cannot_be_blank(session):
    with pytest.raises(IntegrityError):
        make_payment(session, make_open_enquiry(session), payer_phone="   ")


def test_successful_payment_needs_paid_at(session):
    enquiry = make_open_enquiry(session)
    with pytest.raises(IntegrityError):
        make_payment(session, enquiry, status=PaymentStatus.SUCCESSFUL, paid_at=None)


def test_unpaid_payment_cannot_have_paid_at(session):
    enquiry = make_open_enquiry(session)
    with pytest.raises(IntegrityError):
        make_payment(session, enquiry, paid_at=datetime.now(timezone.utc))


def test_failure_reason_only_on_failed_or_cancelled_payment(session):
    enquiry = make_open_enquiry(session)
    with pytest.raises(IntegrityError):
        make_payment(session, enquiry, failure_reason="Insufficient funds")


def test_failed_payment_can_have_a_failure_reason(session):
    payment = make_payment(
        session,
        make_open_enquiry(session),
        status=PaymentStatus.FAILED,
        failure_reason="Insufficient funds",
    )
    assert payment.failure_reason == "Insufficient funds"


def test_payout_cannot_start_before_payment_succeeds(session):
    enquiry = make_open_enquiry(session)
    with pytest.raises(IntegrityError):
        make_payment(session, enquiry, payout_status=PayoutStatus.PENDING)


def test_payout_can_be_pending_after_successful_payment(session):
    payment = make_payment(
        session,
        make_open_enquiry(session),
        status=PaymentStatus.SUCCESSFUL,
        payout_status=PayoutStatus.PENDING,
    )
    assert payment.payout_status == PayoutStatus.PENDING


def test_paid_payout_needs_paid_out_at(session):
    enquiry = make_open_enquiry(session)
    with pytest.raises(IntegrityError):
        make_payment(
            session,
            enquiry,
            status=PaymentStatus.SUCCESSFUL,
            payout_status=PayoutStatus.PAID,
            paid_out_at=None,
        )


def test_paid_out_at_needs_a_paid_payout(session):
    enquiry = make_open_enquiry(session)
    with pytest.raises(IntegrityError):
        make_payment(
            session,
            enquiry,
            status=PaymentStatus.SUCCESSFUL,
            paid_out_at=datetime.now(timezone.utc),
        )


def make_two_enquiries(session):
    location = make_location(session)
    seller = make_business(session, location)
    listing = make_listing(session, seller, location)
    buyers = [
        make_business(session, location, role=BusinessRole.BUYER) for _ in range(2)
    ]
    return [make_enquiry(session, listing, buyer) for buyer in buyers]


def test_momo_transaction_id_must_be_unique(session):
    first, second = make_two_enquiries(session)
    make_payment(session, first, momo_transaction_id="momo-1")
    with pytest.raises(IntegrityError):
        make_payment(session, second, momo_transaction_id="momo-1")


def test_payments_without_a_momo_transaction_id_do_not_clash(session):
    first, second = make_two_enquiries(session)
    make_payment(session, first)
    other = make_payment(session, second)
    assert other.momo_transaction_id is None


def test_enquiry_with_payments_cannot_be_deleted(session):
    enquiry = make_open_enquiry(session)
    make_payment(session, enquiry)
    session.expire_all()
    session.delete(session.get(Enquiry, enquiry.enquiry_id))
    with pytest.raises((IntegrityError, AssertionError)):
        session.flush()
'''


def find_head():
    import re

    pat = r"^{name}\s*(?::[^=]+)?=\s*['\"]([^'\"]+)['\"]"
    revs, downs = set(), set()
    for f in (ROOT / "migrations/versions").glob("*.py"):
        if f.name.startswith("9a2f7"):
            continue
        src = f.read_text()
        r = re.search(pat.format(name="revision"), src, re.M)
        d = re.search(pat.format(name="down_revision"), src, re.M)
        if r:
            revs.add(r.group(1))
        if d:
            downs.add(d.group(1))
    heads = [r for r in revs if r not in downs]
    assert len(heads) == 1, f"expected one alembic head, found {heads}"
    return heads[0]



INTEGRITY_TESTS = """\
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from models import Business, Enquiry, Listing, Location, Payment
from models.business import BusinessRole, BusinessType
from models.listing import ListingType, Stream, Unit
from models.location import OsmType
from models.payment import PaymentStatus, PayoutStatus

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def _business(session, location, role):
    b = Business(
        business_legal_name="Test Co",
        business_role=role,
        business_type=BusinessType.BUSINESS,
        location_id=location.location_id,
        streams=["SAWDUST"],
        contact_email="info@example.rw",
    )
    session.add(b)
    session.flush()
    return b


def _enquiries(session, n=1):
    loc = Location(
        osm_type=OsmType.NODE,
        osm_id=uuid.uuid4().int % 10**9,
        name="Remera",
        display_name="Remera, Kigali, Rwanda",
        latitude=Decimal("-1.956"),
        longitude=Decimal("30.113"),
        district="Gasabo",
        province="Kigali City",
    )
    session.add(loc)
    session.flush()
    seller = _business(session, loc, BusinessRole.SUPPLIER)
    listing = Listing(
        business_id=seller.business_id,
        listing_type=ListingType.RAW_BYPRODUCT,
        stream=Stream.SAWDUST,
        material_or_product="Pine sawdust",
        quantity=Decimal("1000"),
        unit=Unit.KILOGRAM,
        unit_price=Decimal("50"),
        location_id=loc.location_id,
    )
    session.add(listing)
    session.flush()
    out = []
    for _ in range(n):
        buyer = _business(session, loc, BusinessRole.BUYER)
        e = Enquiry(
            listing_id=listing.listing_id,
            buyer_business_id=buyer.business_id,
            seller_business_id=seller.business_id,
            quantity=Decimal("100"),
            unit=Unit.KILOGRAM,
            unit_price=Decimal("50"),
            total_amount=Decimal("5000"),
        )
        session.add(e)
        session.flush()
        out.append(e)
    return out


def _pay(session, enquiry, **kw):
    values = dict(
        enquiry_id=enquiry.enquiry_id,
        amount=Decimal("5000"),
        payer_phone="0788000000",
        reference_id=uuid.uuid4().hex,
    )
    values.update(kw)
    p = Payment(**values)
    session.add(p)
    session.flush()
    return p


def test_payer_phone_cannot_be_blank(session):
    (e,) = _enquiries(session)
    with pytest.raises(IntegrityError):
        _pay(session, e, payer_phone="   ")


def test_successful_payment_needs_paid_at(session):
    (e,) = _enquiries(session)
    with pytest.raises(IntegrityError):
        _pay(session, e, status=PaymentStatus.SUCCESSFUL)


def test_successful_payment_with_paid_at_is_allowed(session):
    (e,) = _enquiries(session)
    p = _pay(session, e, status=PaymentStatus.SUCCESSFUL, paid_at=NOW())
    assert p.paid_at is not None


def test_unpaid_payment_cannot_have_paid_at(session):
    (e,) = _enquiries(session)
    with pytest.raises(IntegrityError):
        _pay(session, e, paid_at=NOW())


def test_failure_reason_only_on_failed_or_cancelled(session):
    (e,) = _enquiries(session)
    with pytest.raises(IntegrityError):
        _pay(session, e, failure_reason="Insufficient funds")


def test_failed_payment_can_have_failure_reason(session):
    (e,) = _enquiries(session)
    p = _pay(session, e, status=PaymentStatus.FAILED, failure_reason="No funds")
    assert p.failure_reason == "No funds"


def test_payout_cannot_start_before_payment_succeeds(session):
    (e,) = _enquiries(session)
    with pytest.raises(IntegrityError):
        _pay(session, e, payout_status=PayoutStatus.PENDING)


def test_payout_pending_after_successful_payment(session):
    (e,) = _enquiries(session)
    p = _pay(
        session,
        e,
        status=PaymentStatus.SUCCESSFUL,
        paid_at=NOW(),
        payout_status=PayoutStatus.PENDING,
    )
    assert p.payout_status == PayoutStatus.PENDING


def test_paid_payout_needs_paid_out_at(session):
    (e,) = _enquiries(session)
    with pytest.raises(IntegrityError):
        _pay(
            session,
            e,
            status=PaymentStatus.SUCCESSFUL,
            paid_at=NOW(),
            payout_status=PayoutStatus.PAID,
        )


def test_paid_out_at_needs_paid_payout(session):
    (e,) = _enquiries(session)
    with pytest.raises(IntegrityError):
        _pay(
            session,
            e,
            status=PaymentStatus.SUCCESSFUL,
            paid_at=NOW(),
            paid_out_at=NOW(),
        )


def test_momo_transaction_id_must_be_unique(session):
    first, second = _enquiries(session, 2)
    _pay(session, first, momo_transaction_id="momo-1")
    with pytest.raises(IntegrityError):
        _pay(session, second, momo_transaction_id="momo-1")


def test_missing_momo_transaction_ids_do_not_clash(session):
    first, second = _enquiries(session, 2)
    _pay(session, first)
    assert _pay(session, second).momo_transaction_id is None
"""


def write(path, text):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    print("wrote", path)


def main():
    write("models/payment.py", MODEL)
    head = find_head()
    print("alembic head is", head)
    write(
        "migrations/versions/9a2f7_payment_integrity.py",
        MIGRATION.replace("Revises: 8c4e1", f"Revises: {head}").replace(
            'Sequence[str], None] = "8c4e1"', f'Sequence[str], None] = "{head}"'
        ),
    )

    patch_existing_tests()
    write("tests/test_payment_integrity.py", INTEGRITY_TESTS)


def patch_existing_tests():
    """Make the old make_payment helper fill paid_at / paid_out_at itself."""
    import re

    tp = ROOT / "tests/test_models.py"
    if not tp.exists():
        print("tests/test_models.py not found - skipped")
        return
    t = tp.read_text()
    if "_fix_payment_dates" in t:
        print("tests/test_models.py already patched")
        return
    m = re.search(r"def make_payment\(.*?\n    values\.update\(changes\)\n", t, re.S)
    if not m:
        print("WARNING: make_payment helper not found in tests/test_models.py;")
        print("         old payment tests using SUCCESSFUL/PAID may need paid_at.")
        return
    inject = (
        "    # _fix_payment_dates: DB needs paid_at when SUCCESSFUL, paid_out_at when PAID\n"
        "    from datetime import datetime as _dt, timezone as _tz\n"
        "    if str(values.get('status')) == 'SUCCESSFUL':\n"
        "        values.setdefault('paid_at', _dt.now(_tz.utc))\n"
        "    if str(values.get('payout_status')) == 'PAID':\n"
        "        values.setdefault('paid_out_at', _dt.now(_tz.utc))\n"
    )
    tp.write_text(t[: m.end()] + inject + t[m.end() :])
    print("patched make_payment in tests/test_models.py")


if __name__ == "__main__":
    main()
