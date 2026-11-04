"""Email building and sending unit tests: no database, no network."""

import io
import json
import logging
import urllib.error
import urllib.request
import uuid

import pytest

from core.config import Settings
from models.user import User
from services.email_service import (
    BrevoEmailSender,
    LoggingEmailSender,
    OutgoingEmail,
    build_email_sender,
    build_password_reset_email,
    build_verification_email,
)

SETTINGS = dict(
    _env_file=None,
    database_url="sqlite://",
    jwt_secret="unit-test-secret-that-is-at-least-32-characters-long",
)


def make_user(first_name="Aline") -> User:
    return User(
        user_id=uuid.uuid4(),
        first_name=first_name,
        last_name="Uwase",
        email="aline@example.rw",
        token_version=0,
    )


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def brevo(monkeypatch):
    calls = {"requests": [], "status": 201, "error": None}

    def fake_urlopen(request, timeout=None):
        calls["requests"].append((request, timeout))
        if calls["error"] is not None:
            raise calls["error"]
        return FakeResponse(calls["status"])

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def sender() -> BrevoEmailSender:
    return BrevoEmailSender(api_key="brevo-key", sender_email="no-reply@huza.ke")


EMAIL = OutgoingEmail(
    to="aline@example.rw",
    subject="Hello",
    text="plain body",
    html="<p>html body</p>",
    link="huza://x",
)


def test_sends_the_message_to_the_brevo_api(brevo):
    sender().send(EMAIL)

    ((request, timeout),) = brevo["requests"]
    assert request.full_url == "https://api.brevo.com/v3/smtp/email"
    assert request.get_method() == "POST"
    assert request.get_header("Api-key") == "brevo-key"
    assert timeout == 10
    body = json.loads(request.data)
    assert body["sender"] == {"name": "HUZA Team", "email": "no-reply@huza.ke"}
    assert body["to"] == [{"email": "aline@example.rw"}]
    assert body["subject"] == "Hello"
    assert body["textContent"] == "plain body"
    assert body["htmlContent"] == "<p>html body</p>"


def test_a_plain_text_message_has_no_html_content(brevo):
    sender().send(OutgoingEmail(to="aline@example.rw", subject="Hi", text="only"))
    body = json.loads(brevo["requests"][0][0].data)
    assert "htmlContent" not in body


def test_send_or_raise_rejects_an_unexpected_status(brevo):
    brevo["status"] = 500
    with pytest.raises(RuntimeError):
        sender().send_or_raise(EMAIL)


def test_send_or_raise_lets_the_error_through(brevo):
    brevo["error"] = urllib.error.URLError("down")
    with pytest.raises(urllib.error.URLError):
        sender().send_or_raise(EMAIL)


def test_a_send_failure_is_logged_and_does_not_crash(brevo, caplog):
    brevo["error"] = urllib.error.URLError("down")
    with caplog.at_level(logging.ERROR, logger="huza.email"):
        sender().send(EMAIL)
    assert "Could not send email" in caplog.text
    assert "aline@example.rw" not in caplog.text


def test_an_http_error_from_brevo_is_logged_without_the_recipient(brevo, caplog):
    brevo["error"] = urllib.error.HTTPError(
        "https://api.brevo.com/v3/smtp/email",
        401,
        "Unauthorized",
        {},
        io.BytesIO(b'{"message":"Key not found"}'),
    )
    with caplog.at_level(logging.ERROR, logger="huza.email"):
        sender().send(EMAIL)
    assert "401" in caplog.text and "Key not found" in caplog.text
    assert "aline@example.rw" not in caplog.text


def test_brevo_is_used_when_an_api_key_is_configured(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "brevo-key")
    chosen = build_email_sender(Settings(**SETTINGS))
    assert isinstance(chosen, BrevoEmailSender)
    assert chosen.api_key == "brevo-key"


def test_without_an_api_key_the_logging_sender_is_used(monkeypatch):
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    assert isinstance(build_email_sender(Settings(**SETTINGS)), LoggingEmailSender)


def test_development_prints_the_link(caplog):
    with caplog.at_level(logging.WARNING, logger="huza.email"):
        LoggingEmailSender(reveal_links=True).send(EMAIL)
    assert "huza://x" in caplog.text


def test_production_never_logs_the_link(caplog):
    with caplog.at_level(logging.WARNING, logger="huza.email"):
        LoggingEmailSender(reveal_links=False).send(EMAIL)
    assert "huza://x" not in caplog.text
    assert "aline@example.rw" not in caplog.text


def test_the_verification_email_carries_a_link_to_the_app():
    settings = Settings(**SETTINGS, email_verify_url="https://app.huza.rw/verify")

    email = build_verification_email(make_user(), settings)

    assert email.to == "aline@example.rw"
    assert email.link.startswith("https://app.huza.rw/verify?token=")
    assert email.link in email.text
    assert email.link in email.html
    assert "24 hours" in email.text


def test_the_reset_email_says_how_long_the_link_lasts():
    settings = Settings(**SETTINGS, reset_token_minutes=45)

    email = build_password_reset_email(make_user(), "482910", settings)

    assert "482910" in email.text
    assert "45 minutes" in email.text


def test_names_are_escaped_in_the_html_version():
    email = build_verification_email(
        make_user(first_name="<script>alert(1)</script>"), Settings(**SETTINGS)
    )
    assert "<script>" not in email.html
    assert "&lt;script&gt;" in email.html
