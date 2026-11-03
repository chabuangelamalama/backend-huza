"""create tables

Revision ID: 51e7454bf6c9
Revises:
Create Date: 2026-10-26 13:21:47.923056

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "51e7454bf6c9"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "locations",
        sa.Column(
            "location_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "osm_type",
            sa.Enum("NODE", "WAY", "RELATION", name="osm_type"),
            nullable=False,
        ),
        sa.Column("osm_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("district", sa.String(length=100), nullable=False),
        sa.Column("province", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("location_id", name=op.f("pk_locations")),
        sa.UniqueConstraint("osm_type", "osm_id", name="uq_locations_osm"),
    )
    op.create_table(
        "businesses",
        sa.Column(
            "business_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("business_legal_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column(
            "business_role",
            sa.Enum("SUPPLIER", "PROCESSOR", "BUYER", name="business_role"),
            nullable=False,
        ),
        sa.Column(
            "business_type",
            sa.Enum(
                "BUSINESS",
                "FARM",
                "COOPERATIVE",
                "INSTITUTION",
                "CONSUMER",
                name="business_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "supplier_kind",
            sa.Enum("PRODUCER", "COLLECTOR", "DEALER", name="supplier_kind"),
            nullable=True,
        ),
        sa.Column("location_id", sa.UUID(), nullable=False),
        sa.Column(
            "streams",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("contact_phone", sa.Text(), nullable=True),
        sa.Column("contact_email", sa.Text(), nullable=False),
        sa.Column("registration_number", sa.String(length=100), nullable=True),
        sa.Column(
            "approval_status",
            sa.Enum(
                "PENDING", "APPROVED", "REJECTED", "SUSPENDED", name="approval_status"
            ),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("payout_phone", sa.Text(), nullable=True),
        sa.Column(
            "payout_network",
            sa.Enum("MPESA", name="payout_network"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "business_type <> 'CONSUMER' OR business_role = 'BUYER'",
            name=op.f("ck_businesses_consumer_only_buyer"),
        ),
        sa.CheckConstraint(
            "streams <@ ARRAY['SAWDUST','PLASTIC','GARMENT_OFFCUTS','GLASS']::text[]",
            name=op.f("ck_businesses_streams_allowed"),
        ),
        sa.CheckConstraint(
            "supplier_kind IS NULL OR business_role = 'SUPPLIER'",
            name=op.f("ck_businesses_supplier_kind_only_supplier"),
        ),
        sa.CheckConstraint(
            "(payout_phone IS NULL) = (payout_network IS NULL)",
            name=op.f("ck_businesses_payout_phone_with_network"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.user_id"],
            name="fk_businesses_approved_by_users",
            ondelete="SET NULL",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.location_id"],
            name=op.f("fk_businesses_location_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("business_id", name=op.f("pk_businesses")),
    )
    op.create_table(
        "listings",
        sa.Column(
            "listing_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column(
            "listing_type",
            sa.Enum("RAW_BYPRODUCT", "FINISHED_PRODUCT", name="listing_type"),
            nullable=False,
        ),
        sa.Column(
            "stream",
            sa.Enum("SAWDUST", "PLASTIC", "GARMENT_OFFCUTS", "GLASS", name="stream"),
            nullable=False,
        ),
        sa.Column("material_or_product", sa.String(length=150), nullable=False),
        sa.Column(
            "specifications",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "photos",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "unit",
            sa.Enum("TONNE", "KILOGRAM", "TRUCKLOAD", "PIECE", "BAG", name="unit"),
            nullable=False,
        ),
        sa.Column("location_id", sa.UUID(), nullable=False),
        sa.Column(
            "sorting_status",
            sa.Enum("SORTED", "PARTLY_SORTED", "MIXED", name="sorting_status"),
            nullable=True,
        ),
        sa.Column("unit_price", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "PUBLISHED",
                "PAUSED",
                "CLOSED",
                "EXPIRED",
                name="listing_status",
            ),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_array_length(photos) <= 5", name=op.f("ck_listings_photos_max_5")
        ),
        sa.CheckConstraint(
            "quantity >= 0", name=op.f("ck_listings_quantity_non_negative")
        ),
        sa.CheckConstraint(
            "unit_price > 0", name=op.f("ck_listings_unit_price_positive")
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.business_id"],
            name=op.f("fk_listings_business_id_businesses"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.location_id"],
            name=op.f("fk_listings_location_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("listing_id", name=op.f("pk_listings")),
        sa.UniqueConstraint(
            "listing_id", "business_id", name="uq_listings_listing_business"
        ),
    )
    op.create_index(
        "ix_listings_search",
        "listings",
        ["status", "stream", "listing_type", "location_id"],
        unique=False,
    )
    op.create_index(
        "ix_listings_specifications_gin",
        "listings",
        ["specifications"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_table(
        "users",
        sa.Column(
            "user_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("business_id", sa.UUID(), nullable=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "user_role",
            sa.Enum("BUSINESS_USER", "ADMIN", name="user_role"),
            server_default=sa.text("'BUSINESS_USER'"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(user_role = 'ADMIN') = (business_id IS NULL)",
            name=op.f("ck_users_user_role_business"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.business_id"],
            name=op.f("fk_users_business_id_businesses"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_users")),
        sa.UniqueConstraint("business_id", name=op.f("uq_users_business_id")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "enquiries",
        sa.Column(
            "enquiry_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("listing_id", sa.UUID(), nullable=False),
        sa.Column("buyer_business_id", sa.UUID(), nullable=False),
        sa.Column("seller_business_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ENQUIRY",
                "AGREED",
                "PAID",
                "COMPLETED",
                "CANCELLED",
                "UNSUCCESSFUL",
                name="enquiry_status",
            ),
            server_default=sa.text("'ENQUIRY'"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column(
            "unit",
            sa.Enum("TONNE", "KILOGRAM", "TRUCKLOAD", "PIECE", "BAG", name="unit"),
            nullable=False,
        ),
        sa.Column("unit_price", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column(
            "failure_reason",
            sa.Enum(
                "NO_PARTNER_FOUND",
                "QUALITY",
                "PRICE",
                "TRANSPORT",
                "QUANTITY",
                "TRUST",
                "PAYMENT",
                "DECLINED",
                "OTHER",
                name="failure_reason",
            ),
            nullable=True,
        ),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status IN ('CANCELLED', 'UNSUCCESSFUL')) = (failure_reason IS NOT NULL)",
            name=op.f("ck_enquiries_failure_reason_required"),
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_enquiries_quantity_positive")),
        sa.CheckConstraint(
            "seller_business_id <> buyer_business_id",
            name=op.f("ck_enquiries_buyer_not_seller"),
        ),
        sa.CheckConstraint(
            "total_amount > 0", name=op.f("ck_enquiries_total_amount_positive")
        ),
        sa.CheckConstraint(
            "unit_price > 0", name=op.f("ck_enquiries_unit_price_positive")
        ),
        sa.ForeignKeyConstraint(
            ["buyer_business_id"],
            ["businesses.business_id"],
            name=op.f("fk_enquiries_buyer_business_id_businesses"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id", "seller_business_id"],
            ["listings.listing_id", "listings.business_id"],
            name="fk_enquiries_seller_owns_listing",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.listing_id"],
            name=op.f("fk_enquiries_listing_id_listings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["seller_business_id"],
            ["businesses.business_id"],
            name=op.f("fk_enquiries_seller_business_id_businesses"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("enquiry_id", name=op.f("pk_enquiries")),
    )
    op.create_index(
        "ix_enquiries_buyer_status",
        "enquiries",
        ["buyer_business_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_enquiries_seller_status",
        "enquiries",
        ["seller_business_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_enquiries_open_per_buyer",
        "enquiries",
        ["listing_id", "buyer_business_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('ENQUIRY', 'AGREED', 'PAID')"),
    )
    op.create_table(
        "price_guides",
        sa.Column(
            "guide_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "stream",
            sa.Enum("SAWDUST", "PLASTIC", "GARMENT_OFFCUTS", "GLASS", name="stream"),
            nullable=False,
        ),
        sa.Column("material", sa.String(length=150), nullable=False),
        sa.Column("grade", sa.String(length=100), nullable=True),
        sa.Column(
            "unit",
            sa.Enum("TONNE", "KILOGRAM", "TRUCKLOAD", "PIECE", "BAG", name="unit"),
            nullable=False,
        ),
        sa.Column("min_price", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("max_price", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("source_date", sa.Date(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=True),
        sa.Column("district", sa.String(length=100), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "max_price >= min_price", name=op.f("ck_price_guides_price_range_order")
        ),
        sa.CheckConstraint(
            "min_price > 0", name=op.f("ck_price_guides_min_price_positive")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.user_id"],
            name=op.f("fk_price_guides_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("guide_id", name=op.f("pk_price_guides")),
    )
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
    op.create_table(
        "notifications",
        sa.Column(
            "notification_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "ENQUIRY_RECEIVED",
                "MESSAGE_RECEIVED",
                "STATUS_CHANGED",
                "PAYMENT_SUCCEEDED",
                "PAYMENT_FAILED",
                "PAYOUT_SENT",
                "LISTING_STALE",
                "APPROVAL_DECISION",
                name="notification_event",
            ),
            nullable=False,
        ),
        sa.Column("enquiry_id", sa.UUID(), nullable=True),
        sa.Column("listing_id", sa.UUID(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["enquiry_id"],
            ["enquiries.enquiry_id"],
            name=op.f("fk_notifications_enquiry_id_enquiries"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.listing_id"],
            name=op.f("fk_notifications_listing_id_listings"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("notification_id", name=op.f("pk_notifications")),
    )
    op.create_index(
        "ix_notifications_user_read",
        "notifications",
        ["user_id", "read_at"],
        unique=False,
    )
    op.create_table(
        "payments",
        sa.Column(
            "payment_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("enquiry_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=19, scale=4), nullable=False),
        sa.Column("payer_phone", sa.Text(), nullable=False),
        sa.Column("reference_id", sa.String(length=100), nullable=False),
        sa.Column("mpesa_transaction_id", sa.String(length=100), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "SUCCESSFUL", "FAILED", "CANCELLED", name="payment_status"
            ),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "payout_status",
            sa.Enum("NOT_DUE", "PENDING", "PAID", "FAILED", name="payout_status"),
            server_default=sa.text("'NOT_DUE'"),
            nullable=False,
        ),
        sa.Column("payout_reference", sa.String(length=100), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payments_amount_positive")),
        sa.ForeignKeyConstraint(
            ["enquiry_id"],
            ["enquiries.enquiry_id"],
            name=op.f("fk_payments_enquiry_id_enquiries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("payment_id", name=op.f("pk_payments")),
        sa.UniqueConstraint("reference_id", name=op.f("uq_payments_reference_id")),
    )
    op.create_index("ix_payments_enquiry_id", "payments", ["enquiry_id"], unique=False)
    op.create_index(
        "uq_payments_one_pending",
        "payments",
        ["enquiry_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "uq_payments_one_successful",
        "payments",
        ["enquiry_id"],
        unique=True,
        postgresql_where=sa.text("status = 'SUCCESSFUL'"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        "uq_payments_one_successful",
        table_name="payments",
        postgresql_where=sa.text("status = 'SUCCESSFUL'"),
    )
    op.drop_index(
        "uq_payments_one_pending",
        table_name="payments",
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.drop_index("ix_payments_enquiry_id", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("messages")
    op.drop_table("price_guides")
    op.drop_index(
        "uq_enquiries_open_per_buyer",
        table_name="enquiries",
        postgresql_where=sa.text("status IN ('ENQUIRY', 'AGREED', 'PAID')"),
    )
    op.drop_index("ix_enquiries_seller_status", table_name="enquiries")
    op.drop_index("ix_enquiries_buyer_status", table_name="enquiries")
    op.drop_table("enquiries")
    op.drop_table("users")
    op.drop_index(
        "ix_listings_specifications_gin", table_name="listings", postgresql_using="gin"
    )
    op.drop_index("ix_listings_search", table_name="listings")
    op.drop_table("listings")
    op.drop_table("businesses")
    op.drop_table("locations")
    # ### end Alembic commands ###
