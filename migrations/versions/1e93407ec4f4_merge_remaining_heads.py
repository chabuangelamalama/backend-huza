"""merge remaining heads

Revision ID: 1e93407ec4f4
Revises: 034cd2b67167, 3180a5f1926a, 34284b4e7eaf, ff920c1ee1f9
Create Date: 2026-11-03 08:25:34.123632

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1e93407ec4f4'
down_revision: Union[str, Sequence[str], None] = ('034cd2b67167', '3180a5f1926a', '34284b4e7eaf', 'ff920c1ee1f9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
