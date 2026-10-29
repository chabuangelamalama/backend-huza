"""user auth columns

Adds the columns the authentication feature needs to app_user: session
revocation (token_version), brute-force protection (failed_login_attempts,
locked_until) and the two-factor columns (mfa_*). Also forces lowercase emails.

Revision ID: c4d2e8a91b73
Revises: 746327295625
Create Date: 2026-10-28 09:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4d2e8a91b73"
down_revision: Union[str, Sequence[str], None] = "746327295625"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "app_user"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "token_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        TABLE, sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(TABLE, sa.Column("mfa_secret_enc", sa.Text(), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "mfa_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(TABLE, sa.Column("last_totp_step", sa.BigInteger(), nullable=True))

    # Existing rows must satisfy the new lowercase rule before it is added.
    op.execute(f"UPDATE {TABLE} SET email = lower(email)")
    op.create_check_constraint(
        op.f("ck_app_user_email_lowercase"), TABLE, "email = lower(email)"
    )
    op.create_check_constraint(
        op.f("ck_app_user_failed_login_attempts_non_negative"),
        TABLE,
        "failed_login_attempts >= 0",
    )
    op.create_check_constraint(
        op.f("ck_app_user_mfa_secret_required"),
        TABLE,
        "mfa_enabled = false OR mfa_secret_enc IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_app_user_mfa_secret_required"), TABLE, type_="check")
    op.drop_constraint(
        op.f("ck_app_user_failed_login_attempts_non_negative"), TABLE, type_="check"
    )
    op.drop_constraint(op.f("ck_app_user_email_lowercase"), TABLE, type_="check")
    op.drop_column(TABLE, "last_totp_step")
    op.drop_column(TABLE, "mfa_enabled")
    op.drop_column(TABLE, "mfa_secret_enc")
    op.drop_column(TABLE, "locked_until")
    op.drop_column(TABLE, "failed_login_attempts")
    op.drop_column(TABLE, "token_version")
