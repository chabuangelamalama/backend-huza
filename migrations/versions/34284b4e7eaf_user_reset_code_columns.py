from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "34284b4e7eaf"
down_revision: Union[str, Sequence[str], None] = "757e2cbca4fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_user", sa.Column("reset_code_hash", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "app_user",
        sa.Column("reset_code_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_user", "reset_code_expires_at")
    op.drop_column("app_user", "reset_code_hash")
