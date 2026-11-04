from pathlib import Path


def test_migration_does_not_drop_user_verification_columns():
    files = [
        Path("migrations/versions/034cd2b67167_update_payment_mpesa_columns.py"),
        Path("migrations/versions/9943f7d9c962_add_mpesa_request_identifiers.py"),
    ]

    for path in files:
        text = path.read_text()
        assert "DROP COLUMN IF EXISTS email_verified_at" not in text
        assert "DROP COLUMN IF EXISTS verify_code_hash" not in text
        assert "DROP COLUMN IF EXISTS verify_code_expires_at" not in text
