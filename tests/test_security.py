"""Pure unit tests: no database needed, so these also run in CI."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from pydantic import ValidationError

from core.config import Settings, normalize_database_url
from core.security import (
    ACCESS,
    RESET,
    TokenError,
    create_access_token,
    create_reset_token,
    decode_token,
    hash_password,
    verify_and_update,
)

SECRET = "unit-test-secret-that-is-at-least-32-characters-long"


def make_settings(**overrides) -> Settings:
    values = dict(database_url="sqlite://", jwt_secret=SECRET)
    values.update(overrides)
    return Settings(_env_file=None, **values)


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #


def test_password_is_hashed_and_verifies():
    hashed = hash_password("Correct1horse")
    assert hashed != "Correct1horse"
    assert hashed.startswith("$argon2id$")
    assert verify_and_update("Correct1horse", hashed)[0] is True


def test_wrong_password_does_not_verify():
    hashed = hash_password("Correct1horse")
    assert verify_and_update("Wrong1horse", hashed)[0] is False


def test_a_corrupt_hash_fails_closed():
    assert verify_and_update("anything1", "x") == (False, None)


def test_two_hashes_of_one_password_differ():
    assert hash_password("Correct1horse") != hash_password("Correct1horse")


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #


def test_access_token_round_trip():
    settings = make_settings()
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id, "ADMIN", 3, settings)

    claims = decode_token(token, ACCESS, settings)

    assert claims.user_id == user_id
    assert claims.token_version == 3
    assert claims.role == "ADMIN"
    assert expires_in == settings.access_token_minutes * 60


def test_a_reset_token_cannot_be_used_as_an_access_token():
    settings = make_settings()
    token = create_reset_token(uuid.uuid4(), 0, settings)
    with pytest.raises(TokenError):
        decode_token(token, ACCESS, settings)


def test_an_access_token_cannot_be_used_to_reset_a_password():
    settings = make_settings()
    token, _ = create_access_token(uuid.uuid4(), "BUSINESS_USER", 0, settings)
    with pytest.raises(TokenError):
        decode_token(token, RESET, settings)


def test_a_token_signed_with_another_secret_is_rejected():
    settings = make_settings()
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tv": 0,
            "typ": ACCESS,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "another-secret-that-is-also-32-characters-long!",
        algorithm="HS256",
    )
    with pytest.raises(TokenError):
        decode_token(forged, ACCESS, settings)


def test_an_expired_token_is_rejected():
    settings = make_settings()
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tv": 0,
            "typ": ACCESS,
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(TokenError):
        decode_token(expired, ACCESS, settings)


def test_garbage_is_rejected():
    with pytest.raises(TokenError):
        decode_token("not-a-jwt", ACCESS, make_settings())


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


def test_a_short_jwt_secret_is_refused():
    with pytest.raises(ValidationError):
        make_settings(jwt_secret="too-short")


def test_auth_settings_have_sensible_defaults():
    settings = make_settings()
    assert settings.access_token_minutes == 30
    assert settings.max_failed_logins == 5
    assert settings.lockout_minutes == 15


def test_the_placeholder_secret_is_refused_in_production():
    placeholder = "replace-with-a-long-random-secret-at-least-32-characters"
    make_settings(jwt_secret=placeholder, environment="development")
    with pytest.raises(ValidationError):
        make_settings(jwt_secret=placeholder, environment="production")


@pytest.mark.parametrize(
    "given, expected",
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg2://u:p@h:5432/db"),
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg2://u:p@h:5432/db"),
        ("postgresql+psycopg2://u:p@h/db", "postgresql+psycopg2://u:p@h/db"),
        ("sqlite://", "sqlite://"),
    ],
)
def test_database_urls_are_normalised(given, expected):
    assert normalize_database_url(given) == expected
