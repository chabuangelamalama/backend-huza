"""update_payment_mpesa_columns

Revision ID: 034cd2b67167
Revises: d8a7a3263aaa
Create Date: 2026-10-30 13:30:35.232774

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import NoSuchTableError

revision: str = "034cd2b67167"
down_revision: Union[str, Sequence[str], None] = "d8a7a3263aaa"
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

    if not _table_exists(bind, "payment_event"):
        op.create_table(
            "payment_event",
            sa.Column(
                "event_id",
                sa.UUID(),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("payment_id", sa.UUID(), nullable=True),
            sa.Column("business_id", sa.UUID(), nullable=True),
            sa.Column("actor_user_id", sa.UUID(), nullable=True),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column(
                "detail",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("clock_timestamp()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["app_user.user_id"],
                name=op.f("fk_payment_event_actor_user_id_app_user"),
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["business_id"],
                ["business.business_id"],
                name=op.f("fk_payment_event_business_id_business"),
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["payment_id"],
                ["payment.payment_id"],
                name=op.f("fk_payment_event_payment_id_payment"),
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("event_id", name=op.f("pk_payment_event")),
        )
    if not _index_exists(bind, "payment_event", "ix_payment_events_business"):
        op.create_index(
            "ix_payment_events_business",
            "payment_event",
            ["business_id", "event_type", "created_at"],
            unique=False,
        )
    if not _index_exists(bind, "payment_event", "ix_payment_events_payment"):
        op.create_index(
            "ix_payment_events_payment",
            "payment_event",
            ["payment_id", "created_at"],
            unique=False,
        )
    for column_name, column in (
        (
            "mpesa_transaction_id",
            sa.Column("mpesa_transaction_id", sa.String(length=100), nullable=True),
        ),
        (
            "mpesa_checkout_request_id",
            sa.Column(
                "mpesa_checkout_request_id", sa.String(length=100), nullable=True
            ),
        ),
        (
            "mpesa_merchant_request_id",
            sa.Column(
                "mpesa_merchant_request_id", sa.String(length=100), nullable=True
            ),
        ),
        (
            "fee_amount",
            sa.Column(
                "fee_amount",
                sa.Numeric(precision=19, scale=4),
                server_default=sa.text("0"),
                nullable=False,
            ),
        ),
        (
            "payout_amount",
            sa.Column(
                "payout_amount", sa.Numeric(precision=19, scale=4), nullable=True
            ),
        ),
        (
            "payout_failure_reason",
            sa.Column("payout_failure_reason", sa.String(length=100), nullable=True),
        ),
        (
            "stock_deducted",
            sa.Column(
                "stock_deducted",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        ),
        (
            "needs_review",
            sa.Column(
                "needs_review",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        ),
        (
            "review_reason",
            sa.Column("review_reason", sa.String(length=200), nullable=True),
        ),
        (
            "refund_status",
            sa.Column(
                "refund_status",
                sa.Enum("NONE", "PENDING", "REFUNDED", "FAILED", name="refund_status"),
                server_default=sa.text("'NONE'"),
                nullable=False,
            ),
        ),
        (
            "refund_reference",
            sa.Column("refund_reference", sa.String(length=100), nullable=True),
        ),
        (
            "refunded_at",
            sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        ),
    ):
        if not _column_exists(bind, "payment", column_name):
            op.add_column("payment", column)

    if not _index_exists(bind, "payment", "ix_payments_needs_review"):
        op.create_index(
            "ix_payments_needs_review",
            "payment",
            ["needs_review"],
            unique=False,
            postgresql_where=sa.text("needs_review"),
        )

    if not _constraint_exists(
        bind, "payment", op.f("uq_payment_mpesa_checkout_request_id")
    ):
        op.create_unique_constraint(
            op.f("uq_payment_mpesa_checkout_request_id"),
            "payment",
            ["mpesa_checkout_request_id"],
        )
    if not _constraint_exists(bind, "payment", op.f("uq_payment_refund_reference")):
        op.create_unique_constraint(
            op.f("uq_payment_refund_reference"), "payment", ["refund_reference"]
        )

    if _column_exists(bind, "payment", "momo_transaction_id"):
        op.drop_column("payment", "momo_transaction_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "payment",
        sa.Column(
            "momo_transaction_id",
            sa.VARCHAR(length=100),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.drop_constraint(op.f("uq_payment_refund_reference"), "payment", type_="unique")
    op.drop_constraint(
        op.f("uq_payment_mpesa_checkout_request_id"), "payment", type_="unique"
    )
    op.drop_index(
        "ix_payments_needs_review",
        table_name="payment",
        postgresql_where=sa.text("needs_review"),
    )
    op.drop_column("payment", "refunded_at")
    op.drop_column("payment", "refund_reference")
    op.drop_column("payment", "refund_status")
    op.drop_column("payment", "review_reason")
    op.drop_column("payment", "needs_review")
    op.drop_column("payment", "stock_deducted")
    op.drop_column("payment", "payout_failure_reason")
    op.drop_column("payment", "payout_amount")
    op.drop_column("payment", "fee_amount")
    op.drop_column("payment", "mpesa_merchant_request_id")
    op.drop_column("payment", "mpesa_checkout_request_id")
    op.drop_column("payment", "mpesa_transaction_id")
    op.add_column(
        "app_user",
        sa.Column(
            "email_verified_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.add_column(
        "app_user",
        sa.Column(
            "verify_code_hash",
            sa.VARCHAR(length=255),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.add_column(
        "app_user",
        sa.Column(
            "verify_code_expires_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.drop_index("ix_payment_events_payment", table_name="payment_event")
    op.drop_index("ix_payment_events_business", table_name="payment_event")
    op.drop_table("payment_event")
