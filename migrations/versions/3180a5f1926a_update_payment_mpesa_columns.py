"""update payment mpesa columns

Revision ID: 3180a5f1926a
Revises: 29012ccabf08
Create Date: 2026-10-30 10:12:07.483257

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3180a5f1926a"
down_revision: Union[str, Sequence[str], None] = "29012ccabf08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        sa.text(
            "ALTER TABLE payment ADD COLUMN IF NOT EXISTS mpesa_transaction_id VARCHAR(100)"
        )
    )
    op.execute(sa.text("ALTER TABLE payment DROP COLUMN IF EXISTS momo_transaction_id"))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        sa.text(
            "ALTER TABLE payment ADD COLUMN IF NOT EXISTS momo_transaction_id VARCHAR(100)"
        )
    )
    op.execute(
        sa.text("ALTER TABLE payment DROP COLUMN IF EXISTS mpesa_transaction_id")
    )
