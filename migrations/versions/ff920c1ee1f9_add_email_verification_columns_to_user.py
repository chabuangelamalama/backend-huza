"""add email verification columns to user

Revision ID: ff920c1ee1f9
Revises: c4d2e8a91b73
Create Date: 2026-10-30 12:07:32.174908

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.exc import NoSuchTableError

revision: str = "ff920c1ee1f9"
down_revision: Union[str, Sequence[str], None] = "c4d2e8a91b73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    try:
        return table_name in inspect(bind).get_table_names()
    except NoSuchTableError:
        return False


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    try:
        return any(
            idx["name"] == index_name for idx in inspect(bind).get_indexes(table_name)
        )
    except NoSuchTableError:
        return False


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    try:
        return any(
            col["name"] == column_name for col in inspect(bind).get_columns(table_name)
        )
    except NoSuchTableError:
        return False


def _constraint_exists(bind, table_name: str, constraint_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    try:
        constraints = inspect(bind).get_unique_constraints(table_name)
        return any(c["name"] == constraint_name for c in constraints)
    except NoSuchTableError:
        return False


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    if _index_exists(bind, "payment_event", "ix_payment_events_business"):
        op.drop_index(op.f("ix_payment_events_business"), table_name="payment_event")
    if _index_exists(bind, "payment_event", "ix_payment_events_payment"):
        op.drop_index(op.f("ix_payment_events_payment"), table_name="payment_event")
    if _table_exists(bind, "payment_event"):
        op.drop_table("payment_event")

    if not _column_exists(bind, "payment", "momo_transaction_id"):
        op.add_column(
            "payment",
            sa.Column("momo_transaction_id", sa.String(length=100), nullable=True),
        )

    if _index_exists(bind, "payment", "ix_payments_needs_review"):
        op.drop_index(
            op.f("ix_payments_needs_review"),
            table_name="payment",
            postgresql_where="needs_review",
        )

    if _constraint_exists(bind, "payment", "uq_payment_mpesa_checkout_request_id"):
        op.drop_constraint(
            op.f("uq_payment_mpesa_checkout_request_id"), "payment", type_="unique"
        )
    if _constraint_exists(bind, "payment", "uq_payment_refund_reference"):
        op.drop_constraint(
            op.f("uq_payment_refund_reference"), "payment", type_="unique"
        )

    for column_name in [
        "needs_review",
        "mpesa_transaction_id",
        "payout_amount",
        "payout_failure_reason",
        "stock_deducted",
        "refund_status",
        "mpesa_merchant_request_id",
        "review_reason",
        "fee_amount",
        "mpesa_checkout_request_id",
        "refund_reference",
        "refunded_at",
    ]:
        if _column_exists(bind, "payment", column_name):
            op.drop_column("payment", column_name)


def downgrade() -> None:
    """Downgrade schema."""
