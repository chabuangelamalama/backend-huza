import html
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from core.config import Settings
from core.security import create_verify_token
from models.user import User

logger = logging.getLogger("huza.email")


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str | None = None
    link: str | None = None


class EmailSender(Protocol):
    def send(self, message: OutgoingEmail) -> None: ...


class BrevoEmailSender:
    """Sends transactional email via Brevo REST API over HTTPS (port 443)."""

    def __init__(self, api_key: str, sender_email: str, sender_name: str = "HUZA Team") -> None:
        self.api_key = api_key
        self.sender_email = sender_email
        self.sender_name = sender_name
        self.endpoint = "https://api.brevo.com/v3/smtp/email"

    def send_or_raise(self, message: OutgoingEmail) -> None:
        payload = {
            "sender": {
                "name": self.sender_name,
                "email": self.sender_email,
            },
            "to": [{"email": message.to}],
            "subject": message.subject,
            "textContent": message.text,
        }
        if message.html:
            payload["htmlContent"] = message.html

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={
                "accept": "application/json",
                "api-key": self.api_key,
                "content-type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 201, 202):
                raise RuntimeError(f"Brevo API error: HTTP {resp.status}")

    def send(self, message: OutgoingEmail) -> None:
        try:
            self.send_or_raise(message)
            logger.info("Successfully sent email %r to %s", message.subject, message.to)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            logger.exception("Brevo HTTP error %s: %s", e.code, error_body)
        except Exception:
            logger.exception("Could not send email %r to %s", message.subject, message.to)


class LoggingEmailSender:
    def __init__(self, reveal_links: bool) -> None:
        self.reveal_links = reveal_links

    def send(self, message: OutgoingEmail) -> None:
        if self.reveal_links:
            logged_item = message.link if message.link else message.text
            logger.warning(
                "EMAIL to %s: %s\n%s", message.to, message.subject, logged_item
            )
        else:
            logger.warning("No BREVO_API_KEY is set, so %r was not sent.", message.subject)


def build_email_sender(settings: Settings) -> EmailSender:
    # Read BREVO_API_KEY from environment or settings
    api_key = getattr(settings, "brevo_api_key", None) or os.getenv("BREVO_API_KEY")
    sender_email = getattr(settings, "email_from", None) or os.getenv("EMAIL_FROM", "chabuangel@gmail.com")

    if api_key:
        return BrevoEmailSender(
            api_key=api_key,
            sender_email=sender_email,
            sender_name="HUZA Team",
        )
    return LoggingEmailSender(reveal_links=not settings.is_production)


def _duration(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{minutes} minutes"


def build_verification_email(user: User, settings: Settings) -> OutgoingEmail:
    token = create_verify_token(user.user_id, user.email, settings)
    link = f"{settings.email_verify_url}?token={token}"
    duration_str = _duration(settings.verify_token_minutes)
    safe_name = html.escape(user.first_name)
    text = (
        f"Hello {user.first_name},\n\n"
        f"Please confirm your email address to finish setting up your account:\n"
        f"{link}\n\n"
        f"This link expires in {duration_str}. If you did not create an account, you can ignore this email.\n\n"
        f"- The HUZA team\n"
    )
    html_body = (
        f'<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:24px;">'
        f"<p>Hello {safe_name},</p>"
        f"<p>Please confirm your email address to finish setting up your account.</p>"
        f'<p><a href="{html.escape(link)}" style="display:inline-block;padding:12px 24px;background:#113225;color:#ffffff;text-decoration:none;border-radius:24px;font-weight:bold;">Confirm email</a></p>'
        f'<p style="color:#666;font-size:13px">This link expires in {duration_str}.</p>'
        f'<p style="color:#666;font-size:13px">The HUZA team</p></div>'
    )
    return OutgoingEmail(
        to=user.email,
        subject="Confirm your HUZA email address",
        text=text,
        html=html_body,
        link=link,
    )


def build_password_reset_email(
    user: User, code: str, settings: Settings
) -> OutgoingEmail:
    safe_name = html.escape(user.first_name)
    subject = "Your HUZA password reset code"
    duration_str = _duration(settings.reset_token_minutes)
    text = (
        f"Hello {user.first_name},\n\n"
        f"We received a request to reset your HUZA password.\n\n"
        f"Your verification code is: {code}\n\n"
        f"This code expires in {duration_str}. If you did not ask for this, you can ignore this email.\n\n"
        f"- The HUZA team\n"
    )
    html_body = f"""\
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f6f8; padding: 40px 20px; margin: 0;">
  <div style="max-width: 480px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 32px; border: 1px solid #e5e7eb;">
    <h2 style="color: #113225; margin-top: 0; font-size: 22px;">Reset your password</h2>
    <p style="color: #4b5563; font-size: 15px; line-height: 1.5;">Hello {safe_name},</p>
    <p style="color: #4b5563; font-size: 15px; line-height: 1.5;">We received a request to reset your HUZA password. Enter the 6-digit code below in the app:</p>
    <div style="text-align: center; margin: 28px 0;">
      <span style="display: inline-block; font-size: 32px; font-weight: 700; letter-spacing: 6px; color: #113225; background-color: #ecfdf5; padding: 14px 28px; border-radius: 8px; border: 1px dashed #059669;">
{code}
      </span>
    </div>

    <p style="color: #6b7280; font-size: 13px; line-height: 1.4;">This code expires in {duration_str} and works once. If you did not request this, you can safely ignore this email.</p>
    <hr style="border: none; border-top: 1px solid #f3f4f6; margin: 24px 0;">
    <p style="color: #9ca3af; font-size: 12px; margin-bottom: 0;">The HUZA team</p>
  </div>
</body>
</html>
"""
    return OutgoingEmail(
        to=user.email,
        subject=subject,
        text=text,
        html=html_body,
    )


def build_verification_code_email(
    user: User, code: str, settings: Settings
) -> OutgoingEmail:
    safe_name = html.escape(user.first_name)
    duration_str = _duration(settings.verify_code_minutes)
    text = (
        f"Hello {user.first_name},\n\n"
        f"Welcome to HUZA. Your email verification code is: {code}\n\n"
        f"This code expires in {duration_str}. If you did not create an account, "
        f"you can ignore this email.\n\n"
        f"- The HUZA team\n"
    )
    html_body = (
        '<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;'
        'padding:24px;">'
        f"<p>Hello {safe_name},</p>"
        "<p>Welcome to HUZA. Enter this code in the app to verify your email:</p>"
        '<p style="font-size:32px;font-weight:700;letter-spacing:6px;color:#113225;">'
        f"{code}</p>"
        f'<p style="color:#666;font-size:13px">This code expires in {duration_str}.</p>'
        '<p style="color:#666;font-size:13px">The HUZA team</p></div>'
    )
    return OutgoingEmail(
        to=user.email,
        subject="Your HUZA email verification code",
        text=text,
        html=html_body,
    )
