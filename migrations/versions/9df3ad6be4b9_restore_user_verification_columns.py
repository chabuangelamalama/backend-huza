"""restore user verification columns

Revision ID: 9df3ad6be4b9
Revises: 1e93407ec4f4
Create Date: 2026-11-03 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "9df3ad6be4b9"
down_revision: Union[str, Sequence[str], None] = "1e93407ec4f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Restore columns required by the user model and auth flow."""
    op.execute(
        """
        ALTER TABLE app_user
            ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;

        ALTER TABLE app_user
            ADD COLUMN IF NOT EXISTS verify_code_hash VARCHAR(255);

        ALTER TABLE app_user
            ADD COLUMN IF NOT EXISTS verify_code_expires_at TIMESTAMPTZ;
        """
    )


def downgrade() -> None:
    """Remove the columns if this migration is reverted."""
    op.execute(
        """
        ALTER TABLE app_user DROP COLUMN IF EXISTS verify_code_expires_at;
        ALTER TABLE app_user DROP COLUMN IF EXISTS verify_code_hash;
        ALTER TABLE app_user DROP COLUMN IF EXISTS email_verified_at;
        """
    )
