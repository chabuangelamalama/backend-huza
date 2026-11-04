"""add mpesa request identifiers

Revision ID: 9943f7d9c962
Revises: d8a7a3263aaa
Create Date: 2026-10-30 10:07:39.054182

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9943f7d9c962"
down_revision: Union[str, Sequence[str], None] = "d8a7a3263aaa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        sa.text("ALTER TABLE app_user DROP COLUMN IF EXISTS password_reset_expires")
    )
    op.execute(
        sa.text("ALTER TABLE app_user DROP COLUMN IF EXISTS password_reset_token")
    )
    op.execute(sa.text("ALTER TABLE app_user DROP COLUMN IF EXISTS email_verified"))
    op.execute(sa.text("ALTER TABLE app_user DROP COLUMN IF EXISTS verification_token"))
    op.add_column(
        "payment",
        sa.Column("mpesa_checkout_request_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "payment",
        sa.Column("mpesa_merchant_request_id", sa.String(length=100), nullable=True),
    )
    op.create_unique_constraint(
        op.f("uq_payment_mpesa_checkout_request_id"),
        "payment",
        ["mpesa_checkout_request_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        sa.text(
            "ALTER TABLE payment DROP CONSTRAINT IF EXISTS "
            "uq_payment_mpesa_checkout_request_id"
        )
    )
    op.execute(
        sa.text("ALTER TABLE payment DROP COLUMN IF EXISTS mpesa_merchant_request_id")
    )
    op.execute(
        sa.text("ALTER TABLE payment DROP COLUMN IF EXISTS mpesa_checkout_request_id")
    )
    op.execute(
        sa.text(
            "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS verification_token VARCHAR"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS "
            "email_verified BOOLEAN NOT NULL DEFAULT false"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS password_reset_token VARCHAR"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE app_user ADD COLUMN IF NOT EXISTS "
            "password_reset_expires TIMESTAMP WITHOUT TIME ZONE"
        )
    )
