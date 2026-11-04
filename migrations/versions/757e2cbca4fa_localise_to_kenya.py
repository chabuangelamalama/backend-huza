from typing import Sequence, Union

from alembic import op


revision: str = "757e2cbca4fa"
down_revision: Union[str, Sequence[str], None] = "c4d2e8a91b73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("location", "district", new_column_name="sub_county")
    op.alter_column("location", "province", new_column_name="county")
    op.alter_column(
        "payment", "momo_transaction_id", new_column_name="mpesa_transaction_id"
    )
    op.execute(
        "UPDATE business SET payout_phone = NULL, payout_network = NULL "
        "WHERE payout_network::text = 'MTN_MOMO'"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_enum
                JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
                WHERE pg_type.typname = 'payout_network' AND pg_enum.enumlabel = 'MTN_MOMO'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_enum
                JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
                WHERE pg_type.typname = 'payout_network' AND pg_enum.enumlabel = 'MPESA'
            ) THEN
                ALTER TYPE payout_network RENAME VALUE 'MTN_MOMO' TO 'MPESA';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "UPDATE business SET payout_phone = NULL, payout_network = NULL "
        "WHERE payout_network::text = 'MPESA'"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_enum
                JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
                WHERE pg_type.typname = 'payout_network' AND pg_enum.enumlabel = 'MPESA'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_enum
                JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
                WHERE pg_type.typname = 'payout_network' AND pg_enum.enumlabel = 'MTN_MOMO'
            ) THEN
                ALTER TYPE payout_network RENAME VALUE 'MPESA' TO 'MTN_MOMO';
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'payment' AND column_name = 'mpesa_transaction_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'payment' AND column_name = 'momo_transaction_id'
            ) THEN
                ALTER TABLE payment
                    RENAME COLUMN mpesa_transaction_id TO momo_transaction_id;
            END IF;
        END
        $$;
        """
    )
    op.alter_column("location", "county", new_column_name="province")
    op.alter_column("location", "sub_county", new_column_name="district")
