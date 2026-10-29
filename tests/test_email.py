"""Email building and sending unit tests: no database, no network."""

import logging
import smtplib
import uuid

import pytest

from core.config import Settings
from models.user import User
from services.email_service import (
    LoggingEmailSender,
    OutgoingEmail,
    SmtpEmailSender,
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


class FakeSMTP:
    """Stands in for smtplib.SMTP / SMTP_SSL and records what happens."""

    instances: list = []
    fail_on_send = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls = []
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message):
        if FakeSMTP.fail_on_send:
            raise smtplib.SMTPException("boom")
        self.sent.append(message)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.fail_on_send = False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def sender(**overrides) -> SmtpEmailSender:
    values = dict(
        host="smtp.example.com",
        port=587,
        username="apikey",
        password="s3cret",
        starttls=True,
        sender="HUZA <no-reply@huza.rw>",
    )
    values.update(overrides)
    return SmtpEmailSender(**values)


EMAIL = OutgoingEmail(
    to="aline@example.rw",
    subject="Hello",
    text="plain body",
    html="<p>html body</p>",
    link="huza://x",
)


# --------------------------------------------------------------------------- #
# SMTP sender
# --------------------------------------------------------------------------- #


def test_sends_with_starttls_and_login(smtp):
    sender().send(EMAIL)

    (connection,) = smtp.instances
    assert (connection.host, connection.port) == ("smtp.example.com", 587)
    assert connection.calls == ["starttls", ("login", "apikey", "s3cret")]
    (message,) = connection.sent
    assert message["To"] == "aline@example.rw"
    assert message["From"] == "HUZA <no-reply@huza.rw>"
    assert message["Subject"] == "Hello"
    assert message.get_body(("plain",)).get_content().strip() == "plain body"
    assert "html body" in message.get_body(("html",)).get_content()


def test_a_connection_without_credentials_skips_login(smtp):
    sender(username=None, password=None, starttls=False).send(EMAIL)
    assert smtp.instances[0].calls == []


def test_port_465_uses_implicit_ssl_and_no_starttls(smtp):
    sender(port=465).send(EMAIL)
    assert "starttls" not in smtp.instances[0].calls


def test_send_or_raise_lets_the_error_through(smtp):
    smtp.fail_on_send = True
    with pytest.raises(smtplib.SMTPException):
        sender().send_or_raise(EMAIL)


def test_a_send_failure_is_logged_and_does_not_crash(smtp, caplog):
    smtp.fail_on_send = True
    with caplog.at_level(logging.ERROR, logger="huza.email"):
        sender().send(EMAIL)  # must not raise: it runs after the response is sent
    assert "Could not send email" in caplog.text
    assert "aline@example.rw" not in caplog.text  # no personal data in the logs


# --------------------------------------------------------------------------- #
# Choosing a sender
# --------------------------------------------------------------------------- #


def test_smtp_is_used_when_a_host_is_configured():
    settings = Settings(**SETTINGS, smtp_host="smtp.example.com")
    assert isinstance(build_email_sender(settings), SmtpEmailSender)


def test_a_blank_host_falls_back_to_the_logging_sender():
    settings = Settings(**SETTINGS, smtp_host="")
    assert isinstance(build_email_sender(settings), LoggingEmailSender)


def test_development_prints_the_link(caplog):
    with caplog.at_level(logging.WARNING, logger="huza.email"):
        LoggingEmailSender(reveal_links=True).send(EMAIL)
    assert "huza://x" in caplog.text


def test_production_never_logs_the_link(caplog):
    with caplog.at_level(logging.WARNING, logger="huza.email"):
        LoggingEmailSender(reveal_links=False).send(EMAIL)
    assert "huza://x" not in caplog.text
    assert "aline@example.rw" not in caplog.text


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #


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

    email = build_password_reset_email(make_user(), settings)

    assert email.link.startswith("huza://reset-password?token=")
    assert "45 minutes" in email.text


def test_names_are_escaped_in_the_html_version():
    email = build_verification_email(
        make_user(first_name="<script>alert(1)</script>"), Settings(**SETTINGS)
    )
    assert "<script>" not in email.html
    assert "&lt;script&gt;" in email.html
