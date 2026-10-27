"""singular table names

Revision ID: 746327295625
Revises: 51e7454bf6c9
Create Date: 2026-10-27 12:29:59.283742

"""

from typing import Sequence, Union

from alembic import op


revision: str = "746327295625"
down_revision: Union[str, Sequence[str], None] = "51e7454bf6c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RENAMES = {
    "businesses": "business",
    "enquiries": "enquiry",
    "listings": "listing",
    "locations": "location",
    "messages": "message",
    "notifications": "notification",
    "payments": "payment",
    "price_guides": "price_guide",
    "users": "app_user",
}


def upgrade() -> None:
    for old, new in RENAMES.items():
        op.rename_table(old, new)


def downgrade() -> None:
    for old, new in RENAMES.items():
        op.rename_table(new, old)
