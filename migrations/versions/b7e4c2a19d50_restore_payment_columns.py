"""restore payment columns and payment_event table

Migration ff920c1ee1f9 drops the M-Pesa / payout / refund columns from
`payment` and the `payment_event` table. This puts them back. Every step
checks first, so it is safe on a database that is already correct.

Revision ID: b7e4c2a19d50
Revises: 9df3ad6be4b9
Create Date: 2026-11-03 23:30:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "b7e4c2a19d50"
down_revision: Union[str, Sequence[str], None] = "9df3ad6be4b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE refund_status AS ENUM ('NONE', 'PENDING', 'REFUNDED', 'FAILED');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;

        ALTER TABLE payment
            ADD COLUMN IF NOT EXISTS mpesa_transaction_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS mpesa_checkout_request_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS mpesa_merchant_request_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS fee_amount NUMERIC(19, 4) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS payout_amount NUMERIC(19, 4),
            ADD COLUMN IF NOT EXISTS payout_failure_reason VARCHAR(100),
            ADD COLUMN IF NOT EXISTS stock_deducted BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS needs_review BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS review_reason VARCHAR(200),
            ADD COLUMN IF NOT EXISTS refund_status refund_status NOT NULL DEFAULT 'NONE',
            ADD COLUMN IF NOT EXISTS refund_reference VARCHAR(100),
            ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMPTZ;

        ALTER TABLE payment DROP COLUMN IF EXISTS momo_transaction_id;

        DO $$ BEGIN
            ALTER TABLE payment ADD CONSTRAINT uq_payment_mpesa_checkout_request_id
                UNIQUE (mpesa_checkout_request_id);
        EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
        END $$;

        DO $$ BEGIN
            ALTER TABLE payment ADD CONSTRAINT uq_payment_refund_reference
                UNIQUE (refund_reference);
        EXCEPTION WHEN duplicate_object OR duplicate_table THEN NULL;
        END $$;

        DO $$ BEGIN
            ALTER TABLE payment ADD CONSTRAINT ck_payment_fee_non_negative
                CHECK (fee_amount >= 0);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;

        DO $$ BEGIN
            ALTER TABLE payment ADD CONSTRAINT ck_payment_payout_split_matches_amount
                CHECK (payout_amount IS NULL
                       OR (payout_amount > 0 AND payout_amount + fee_amount = amount));
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;

        CREATE INDEX IF NOT EXISTS ix_payments_needs_review
            ON payment (needs_review) WHERE needs_review;

        CREATE TABLE IF NOT EXISTS payment_event (
            event_id UUID NOT NULL DEFAULT gen_random_uuid(),
            payment_id UUID,
            business_id UUID,
            actor_user_id UUID,
            event_type VARCHAR(50) NOT NULL,
            detail JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT pk_payment_event PRIMARY KEY (event_id),
            CONSTRAINT fk_payment_event_payment_id_payment
                FOREIGN KEY (payment_id) REFERENCES payment (payment_id)
                ON DELETE RESTRICT,
            CONSTRAINT fk_payment_event_business_id_business
                FOREIGN KEY (business_id) REFERENCES business (business_id)
                ON DELETE RESTRICT,
            CONSTRAINT fk_payment_event_actor_user_id_app_user
                FOREIGN KEY (actor_user_id) REFERENCES app_user (user_id)
                ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS ix_payment_events_payment
            ON payment_event (payment_id, created_at);
        CREATE INDEX IF NOT EXISTS ix_payment_events_business
            ON payment_event (business_id, event_type, created_at);
        """
    )


def downgrade() -> None:
    pass
