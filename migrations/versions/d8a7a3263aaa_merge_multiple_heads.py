"""merge multiple heads

Revision ID: d8a7a3263aaa
Revises: 295fb6f38a6a, c4d2e8a91b73
Create Date: 2026-10-30 10:03:17.956533

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "d8a7a3263aaa"
down_revision: Union[str, Sequence[str], None] = ("295fb6f38a6a", "c4d2e8a91b73")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
