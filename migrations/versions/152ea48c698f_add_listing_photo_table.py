"""add listing photo table

Revision ID: 152ea48c698f
Revises: 746327295625
Create Date: 2026-10-28 08:26:12.813384

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "152ea48c698f"
down_revision: Union[str, Sequence[str], None] = "746327295625"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "listing_photo",
        sa.Column(
            "photo_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("listing_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column(
            "content_type",
            sa.String(length=50),
            server_default=sa.text("'image/webp'"),
            nullable=False,
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_type = 'image/webp'",
            name=op.f("ck_listing_photo_content_type_webp"),
        ),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 5", name=op.f("ck_listing_photo_position_1_to_5")
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 5242880",
            name=op.f("ck_listing_photo_size_bytes_range"),
        ),
        sa.CheckConstraint(
            "width > 0 AND height > 0",
            name=op.f("ck_listing_photo_dimensions_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listing.listing_id"],
            name=op.f("fk_listing_photo_listing_id_listing"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("photo_id", name=op.f("pk_listing_photo")),
        sa.UniqueConstraint("listing_id", "position", name="uq_listing_photo_position"),
    )
    op.drop_column("listing", "photos")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "listing",
        sa.Column(
            "photos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            autoincrement=False,
            nullable=False,
        ),
    )
    op.drop_table("listing_photo")
    op.create_check_constraint(
        "ck_listing_photos_max_5", "listing", "jsonb_array_length(photos) <= 5"
    )
