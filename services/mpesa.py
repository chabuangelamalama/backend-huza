import base64
import hashlib
import hmac
import logging
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

import httpx

from core.payment_config import MpesaSettings

log = logging.getLogger("huza.mpesa")

Product = Literal["collection", "disbursement"]


class MpesaError(Exception):
    """Base exception for Safaricom M-Pesa interactions."""


class MpesaRejected(MpesaError):
    """Safaricom explicitly refused the request (4xx). The money movement did not start."""

    def __init__(self, reason: str | None):
        super().__init__(reason or "REJECTED")
        self.reason = reason


class MpesaTransient(MpesaError):
    """Timeout, 5xx, or network connection failure. Transaction status is unknown."""


@dataclass(frozen=True)
class MpesaResult:
    status: Literal["PENDING", "SUCCESSFUL", "FAILED"]
    amount: Decimal | None
    currency: str | None
    external_id: str | None
    financial_transaction_id: str | None
    reason: str | None


class MpesaGateway(Protocol):
    """Protocol interface defining allowed operational calls against the Safaricom footprint."""

    def request_to_pay(self, **kw) -> str: ...
    def get_request_to_pay(self, checkout_request_id: str) -> "MpesaResult | None": ...
    def transfer(self, **kw) -> None: ...
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
    """Enforces absolute integer formatting constraints for transactional values."""
    if amount <= 0 or amount != amount.to_integral_value():
        raise ValueError("Amount must be a positive whole number")
    return str(int(amount))


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

            credentials = f"{self.s.consumer_key.get_secret_value()}:{self.s.consumer_secret.get_secret_value()}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()

            headers = {"Authorization": f"Basic {encoded_credentials}"}
            url = "/oauth/v1/generate?grant_type=client_credentials"

            try:
                r = self.http.get(url, headers=headers)
            except httpx.HTTPError as e:
                raise MpesaTransient("Token request failed") from e

            if r.status_code != 200:
                log.error("M-Pesa token generation error status=%s", r.status_code)
                raise MpesaTransient("Token request rejected by Safaricom")

            body = r.json()
            token = body["access_token"]
            ttl = int(body.get("expires_in", 3600))
            self._token_cache = (token, time.monotonic() + ttl)
            return token

    def _callback_url(self, kind: Product, reference_id: str) -> str:
        base = self.s.callback_base_url.rstrip("/")
        return f"{base}/payments/mpesa/callback/{kind}/{reference_id}"

    def request_to_pay(
        self,
        *,
        reference_id: str,
        amount: Decimal,
        phone_number: str,
        account_reference: str,
        transaction_desc: str,
    ) -> str:
        """Dispatches an operational STK Push request to the buyer's handset."""
        token = self._get_token()
        timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())

        password_str = f"{self.s.express_shortcode}{self.s.express_passkey.get_secret_value()}{timestamp}"
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
            "TransactionDesc": transaction_desc[:20],
        }

        try:
            r = self.http.post(
                "/mpesa/stkpush/v1/processrequest", json=payload, headers=headers
            )
        except httpx.HTTPError as e:
            raise MpesaTransient(
                "Network connection error during STK Push request"
            ) from e

        if r.status_code == 200:
            body = r.json()
            response_code = body.get("ResponseCode")
            if response_code == "0":
                return body["CheckoutRequestID"]
            raise MpesaRejected(body.get("ResponseDescription"))

        if r.status_code >= 500 or r.status_code == 429:
            raise MpesaTransient(
                f"Safaricom returned standard error status {r.status_code}"
            )

        raise MpesaRejected(
            f"STK Push request rejected with status code {r.status_code}"
        )

    def get_request_to_pay(self, checkout_request_id: str) -> MpesaResult | None:
        """Polls Safaricom backend node to query specific CheckoutRequestID processing state."""
        token = self._get_token()
        timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())

        password_str = f"{self.s.express_shortcode}{self.s.express_passkey.get_secret_value()}{timestamp}"
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
            r = self.http.post("/mpesa/stkpush/v1/query", json=payload, headers=headers)
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
        result_code = b.get("ResultCode")

        if result_code == "0":
            status = "SUCCESSFUL"
        elif result_code in ["1032", "1037", "2001"]:
            status = "FAILED"
        else:
            status = "PENDING"

        return MpesaResult(
            status=status,
            amount=None,
            currency=self.s.currency,
            external_id=checkout_request_id,
            financial_transaction_id=b.get("ResultDesc"),
            reason=b.get("ResultDesc"),
        )
