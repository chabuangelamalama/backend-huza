"""payments feature: fee, refund, review flags, audit table

Revision ID: a1b2c3d4e5f6
Revises: 746327295625
Create Date: 2026-10-28 09:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "746327295625"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REFUND_VALUES = ("NONE", "PENDING", "REFUNDED", "FAILED")


def upgrade() -> None:
    refund_status = postgresql.ENUM(*REFUND_VALUES, name="refund_status")
    refund_status.create(op.get_bind(), checkfirst=True)
    refund_col = postgresql.ENUM(
        *REFUND_VALUES, name="refund_status", create_type=False
    )

    op.add_column(
        "payment",
        sa.Column(
            "fee_amount", sa.Numeric(19, 4), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        "payment", sa.Column("payout_amount", sa.Numeric(19, 4), nullable=True)
    )
    op.add_column(
        "payment", sa.Column("payout_failure_reason", sa.String(100), nullable=True)
    )
    op.add_column(
        "payment",
        sa.Column(
            "stock_deducted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "payment",
        sa.Column(
            "needs_review",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("payment", sa.Column("review_reason", sa.String(200), nullable=True))
    op.add_column(
        "payment",
        sa.Column(
            "refund_status",
            refund_col,
            server_default=sa.text("'NONE'"),
            nullable=False,
        ),
    )
    op.add_column(
        "payment", sa.Column("refund_reference", sa.String(100), nullable=True)
    )
    op.add_column(
        "payment", sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint(
        op.f("uq_payment_refund_reference"), "payment", ["refund_reference"]
    )
    op.create_check_constraint(
        op.f("ck_payment_fee_non_negative"), "payment", "fee_amount >= 0"
    )
    op.create_check_constraint(
        op.f("ck_payment_payout_split_matches_amount"),
        "payment",
        "payout_amount IS NULL OR "
        "(payout_amount > 0 AND payout_amount + fee_amount = amount)",
    )
    op.create_index(
        "ix_payments_needs_review",
        "payment",
        ["needs_review"],
        postgresql_where=sa.text("needs_review"),
    )

    op.create_table(
        "payment_event",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(),
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
            ["payment_id"],
            ["payment.payment_id"],
            name=op.f("fk_payment_event_payment_id_payment"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["business.business_id"],
            name=op.f("fk_payment_event_business_id_business"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["app_user.user_id"],
            name=op.f("fk_payment_event_actor_user_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_payment_event")),
    )
    op.create_index(
        "ix_payment_events_payment", "payment_event", ["payment_id", "created_at"]
    )
    op.create_index(
        "ix_payment_events_business",
        "payment_event",
        ["business_id", "event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_events_business", table_name="payment_event")
    op.drop_index("ix_payment_events_payment", table_name="payment_event")
    op.drop_table("payment_event")
    op.drop_index("ix_payments_needs_review", table_name="payment")
    op.drop_constraint(
        op.f("ck_payment_payout_split_matches_amount"), "payment", type_="check"
    )
    op.drop_constraint(op.f("ck_payment_fee_non_negative"), "payment", type_="check")
    op.drop_constraint(op.f("uq_payment_refund_reference"), "payment", type_="unique")
    for col in (
        "refunded_at",
        "refund_reference",
        "refund_status",
        "review_reason",
        "needs_review",
        "stock_deducted",
        "payout_failure_reason",
        "payout_amount",
        "fee_amount",
    ):
        op.drop_column("payment", col)
    postgresql.ENUM(name="refund_status").drop(op.get_bind(), checkfirst=True)
