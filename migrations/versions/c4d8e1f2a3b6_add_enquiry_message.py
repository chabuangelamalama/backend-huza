"""add enquiry message

The buyer's opening message (pickup notes, questions) sent with an enquiry.

Revision ID: c4d8e1f2a3b6
Revises: b7e4c2a19d50
Create Date: 2026-11-05 01:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4d8e1f2a3b6"
down_revision: Union[str, Sequence[str], None] = "b7e4c2a19d50"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("enquiry", sa.Column("message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("enquiry", "message")
