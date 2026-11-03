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
        "WHERE payout_network = 'MTN_MOMO'"
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
        "WHERE payout_network = 'MPESA'"
    )
    op.execute("ALTER TYPE payout_network RENAME VALUE 'MPESA' TO 'MTN_MOMO'")
    op.alter_column(
        "payment", "mpesa_transaction_id", new_column_name="momo_transaction_id"
    )
    op.alter_column("location", "county", new_column_name="province")
    op.alter_column("location", "sub_county", new_column_name="district")
