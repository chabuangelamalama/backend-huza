"""Safaricom Daraja API client (OAuth, STK Push, Callback Verification, B2C)."""

import base64
import hashlib
import hmac
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Protocol

import httpx

from core.payment_config import MpesaSettings

log = logging.getLogger("huza.mpesa")

Product = Literal["collection", "disbursement"]
EAT_TIMEZONE = timezone(timedelta(hours=3))
STK_STILL_PROCESSING = 4999


class MpesaError(Exception):
    """Base exception for Safaricom M-Pesa interactions."""


class MpesaRejected(MpesaError):
    """Safaricom explicitly refused the request (4xx)."""

    def __init__(self, reason: str | None):
        super().__init__(reason or "REJECTED")
        self.reason = reason


class MpesaTransient(MpesaError):
    """Timeout, 5xx, or network connection failure."""


@dataclass(frozen=True)
class MpesaResult:
    status: Literal["PENDING", "SUCCESSFUL", "FAILED"]
    amount: Decimal | None
    currency: str | None
    external_id: str | None
    financial_transaction_id: str | None
    reason: str | None
    result_code: int | None = None


class MpesaGateway(Protocol):
    """Protocol interface defining allowed operational calls against Safaricom."""

    def request_to_pay(self, **kw) -> str: ...
    def get_request_to_pay(self, checkout_request_id: str) -> "MpesaResult | None": ...
    def transfer(self, **kw) -> str: ...
    def get_transfer(self, reference_id: str) -> "MpesaResult | None": ...


def callback_token(secret: str, kind: Product, reference_id: str) -> str:
    """Computes a secure payment verification token sign for callbacks."""
    msg = f"{kind}:{reference_id}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify_callback_token(
    secret: str, kind: Product, reference_id: str, token: str
) -> bool:
    if not secret:
        return False
    return hmac.compare_digest(callback_token(secret, kind, reference_id), token)


def to_mpesa_amount(amount: Decimal) -> str:
    """Enforces integer formatting constraints for transactional values."""
    if amount <= 0 or amount != amount.to_integral_value():
        raise ValueError("Amount must be a positive whole number")
    return str(int(amount))


def _get_eat_timestamp() -> str:
    """Generates the YYYYMMDDHHmmss timestamp in East Africa Time (EAT)."""
    return datetime.now(EAT_TIMEZONE).strftime("%Y%m%d%H%M%S")


class MpesaClient:
    def __init__(self, settings: MpesaSettings, http: httpx.Client | None = None):
        self.s = settings
        self.http = http or httpx.Client(
            base_url=settings.base_url.rstrip("/"),
            timeout=settings.http_timeout_seconds,
            follow_redirects=False,
        )
        self._token_cache: tuple[str, float] = ("", 0.0)
        self._lock = threading.Lock()

    def _get_token(self) -> str:
        """Requests a valid Daraja OAuth Access Token using Basic App Authentication."""
        with self._lock:
            token, expiry = self._token_cache
            if token and expiry > time.monotonic() + 30:
                return token

            credentials = (
                f"{self.s.consumer_key.get_secret_value()}:"
                f"{self.s.consumer_secret.get_secret_value()}"
            )
            encoded_credentials = base64.b64encode(credentials.encode()).decode()

            headers = {"Authorization": f"Basic {encoded_credentials}"}
            url = "/oauth/v1/generate?grant_type=client_credentials"

            try:
                r = self.http.get(url, headers=headers)
            except httpx.HTTPError as e:
                raise MpesaTransient("Token request failed") from e

            if r.status_code != 200:
                log.error(
                    "M-Pesa token generation error status=%s body=%s",
                    r.status_code,
                    r.text,
                )
                raise MpesaTransient("Token request rejected by Safaricom")

            body = r.json()
            token = body["access_token"]
            ttl = int(body.get("expires_in", 3600))
            self._token_cache = (token, time.monotonic() + ttl)
            return token

    def _callback_url(self, kind: Product, reference_id: str) -> str:
        """Constructs the full public callback URL including the HMAC security token."""
        base = self.s.callback_base_url.rstrip("/")
        secret = self.s.callback_secret.get_secret_value()
        token = callback_token(secret, kind, reference_id)
        return f"{base}/payments/mpesa/callback/{kind}/{reference_id}/{token}"

    def request_to_pay(
        self,
        *,
        reference_id: str,
        amount: Decimal,
        phone_number: str,
        account_reference: str,
        transaction_desc: str,
    ) -> str:
        """Dispatches an operational STK Push request to the buyer handset."""
        token = self._get_token()
        timestamp = _get_eat_timestamp()

        password_str = (
            f"{self.s.express_shortcode}"
            f"{self.s.express_passkey.get_secret_value()}"
            f"{timestamp}"
        )
        password = base64.b64encode(password_str.encode()).decode()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "BusinessShortCode": self.s.express_shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": to_mpesa_amount(amount),
            "PartyA": phone_number,
            "PartyB": self.s.express_shortcode,
            "PhoneNumber": phone_number,
            "CallBackURL": self._callback_url("collection", reference_id),
            "AccountReference": account_reference[:12],
            "TransactionDesc": transaction_desc[:13],
        }

        try:
            r = self.http.post(
                "/mpesa/stkpush/v1/processrequest",
                json=payload,
                headers=headers,
            )
        except httpx.HTTPError as e:
            raise MpesaTransient(
                "Network connection error during STK Push request"
            ) from e

        if r.status_code == 200:
            body = r.json()
            response_code = body.get("ResponseCode")
            if str(response_code) == "0":
                return body["CheckoutRequestID"]
            raise MpesaRejected(body.get("ResponseDescription"))

        if r.status_code >= 500 or r.status_code == 429:
            raise MpesaTransient(
                f"Safaricom returned standard error status {r.status_code}"
            )

        err_msg = None
        try:
            err_json = r.json()
            err_msg = err_json.get("errorMessage") or err_json.get(
                "ResponseDescription"
            )
        except Exception:
            pass

        raise MpesaRejected(
            err_msg or f"STK Push request rejected with status code {r.status_code}"
        )

    def get_request_to_pay(self, checkout_request_id: str) -> MpesaResult | None:
        """Polls Safaricom backend node to query specific CheckoutRequestID processing state."""
        token = self._get_token()
        timestamp = _get_eat_timestamp()

        password_str = (
            f"{self.s.express_shortcode}"
            f"{self.s.express_passkey.get_secret_value()}"
            f"{timestamp}"
        )
        password = base64.b64encode(password_str.encode()).decode()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "BusinessShortCode": self.s.express_shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }

        try:
            r = self.http.post(
                "/mpesa/stkpushquery/v1/query",
                json=payload,
                headers=headers,
            )
        except httpx.HTTPError as e:
            raise MpesaTransient(
                "Network connection error during transaction status query"
            ) from e

        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise MpesaTransient(
                f"Safaricom status check returned error status {r.status_code}"
            )

        b = r.json()
        raw_result_code = b.get("ResultCode")

        result_code_int: int | None = None
        if raw_result_code is not None:
            try:
                result_code_int = int(raw_result_code)
            except (ValueError, TypeError):
                pass

        if result_code_int == 0:
            status = "SUCCESSFUL"
        elif result_code_int is None or result_code_int == STK_STILL_PROCESSING:
            # 4999 "The transaction is still under processing": the buyer may
            # still be entering their PIN, so this is not a result yet.
            status = "PENDING"
        else:
            status = "FAILED"

        return MpesaResult(
            status=status,
            amount=None,
            currency=self.s.currency,
            external_id=checkout_request_id,
            financial_transaction_id=b.get("ResultDesc"),
            reason=b.get("ResultDesc"),
            result_code=result_code_int,
        )

    def transfer(
        self,
        *,
        reference_id: str,
        amount: Decimal,
        phone_number: str,
        remarks: str = "Athena Payout",
        occasion: str = "",
    ) -> str:
        """Dispatches an M-Pesa B2C payout to a recipient phone number."""
        token = self._get_token()
        callback_url = self._callback_url("disbursement", reference_id)

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        sec_cred_val = self.s.security_credential.get_secret_value()
        party_a = self.s.b2c_shortcode
        initiator_name = self.s.initiator_name

        missing = [
            name
            for name, value in (
                ("MPESA_B2C_SHORTCODE", party_a),
                ("MPESA_INITIATOR_NAME", initiator_name),
                ("MPESA_SECURITY_CREDENTIAL", sec_cred_val),
            )
            if not value
        ]
        if missing:
            raise MpesaRejected("B2C payouts are not configured: " + ", ".join(missing))

        payload = {
            "InitiatorName": initiator_name,
            "SecurityCredential": sec_cred_val,
            "CommandID": "BusinessPayment",
            "Amount": to_mpesa_amount(amount),
            "PartyA": str(party_a),
            "PartyB": phone_number,
            "Remarks": remarks[:100] or "Payout",
            "QueueTimeOutURL": callback_url,
            "ResultURL": callback_url,
            "Occasion": occasion[:100],
        }

        try:
            r = self.http.post(
                "/mpesa/b2c/v1/paymentrequest",
                json=payload,
                headers=headers,
            )
        except httpx.HTTPError as e:
            raise MpesaTransient("Network error during B2C transfer") from e

        if r.status_code == 200:
            body = r.json()
            if str(body.get("ResponseCode")) == "0":
                return body.get("ConversationID", reference_id)
            raise MpesaRejected(
                body.get("ResponseDescription") or "B2C rejected by Daraja"
            )

        err_msg = None
        try:
            err_json = r.json()
            err_msg = (
                err_json.get("errorMessage")
                or err_json.get("ResponseDescription")
                or str(err_json)
            )
        except Exception:
            err_msg = r.text

        raise MpesaRejected(
            f"B2C payout rejected with status {r.status_code}: {err_msg}"
        )

    def get_transfer(self, reference_id: str) -> MpesaResult | None:
        """Query transfer status if needed (B2C relies on asynchronous callbacks)."""
        return None
