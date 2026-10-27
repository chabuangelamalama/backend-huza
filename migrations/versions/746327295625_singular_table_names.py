"""singular table names

Revision ID: 746327295625
Revises: 51e7454bf6c9
Create Date: 2026-10-27 12:29:59.283742

"""

from typing import Sequence, Union

import sqlalchemy as sa
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
    "notifications": "notification",
    "payments": "payment",
    "price_guides": "price_guide",
    "users": "app_user",
}

CONSTRAINT_RENAMES = [
    ("app_user", "uq_users_business_id", "uq_app_user_business_id"),
    ("app_user", "uq_users_email", "uq_app_user_email"),
    ("payment", "uq_payments_reference_id", "uq_payment_reference_id"),
]


def upgrade() -> None:
    op.drop_table("messages")
    for old, new in RENAMES.items():
        op.rename_table(old, new)
    for table, old, new in CONSTRAINT_RENAMES:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")


def downgrade() -> None:
    for table, old, new in CONSTRAINT_RENAMES:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {new} TO {old}")
    for old, new in RENAMES.items():
        op.rename_table(new, old)
    op.create_table(
        "messages",
        sa.Column(
            "message_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("enquiry_id", sa.UUID(), nullable=False),
        sa.Column("sender_user_id", sa.UUID(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(body) <= 2000", name=op.f("ck_messages_body_max_2000")
        ),
        sa.ForeignKeyConstraint(
            ["enquiry_id"],
            ["enquiries.enquiry_id"],
            name=op.f("fk_messages_enquiry_id_enquiries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sender_user_id"],
            ["users.user_id"],
            name=op.f("fk_messages_sender_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("message_id", name=op.f("pk_messages")),
    )
