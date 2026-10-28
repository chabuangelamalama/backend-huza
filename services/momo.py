"""Thin client for the MTN MoMo Open API (Collection + Disbursement).

Rules this client follows:
  * Base URL, keys and callback URL come ONLY from settings (no user-supplied URLs: SSRF).
  * TLS verification is never disabled. Every call has a timeout.
  * Secrets, tokens and phone numbers are never logged.
  * Anything returned by MTN is treated as untrusted and validated.
"""

import hashlib
import hmac
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

import httpx

from core.payment_config import MomoSettings

log = logging.getLogger("huza.momo")

Product = Literal["collection", "disbursement"]


class MomoError(Exception):
    """Base class."""


class MomoRejected(MomoError):
    """MTN refused the request (4xx). The money movement definitely did not start."""

    def __init__(self, reason: str | None):
        super().__init__(reason or "REJECTED")
        self.reason = reason


class MomoTransient(MomoError):
    """Timeout / 5xx / network error. Outcome UNKNOWN: reconcile by reading the status."""


@dataclass(frozen=True)
class MomoResult:
    status: Literal["PENDING", "SUCCESSFUL", "FAILED"]
    amount: Decimal | None
    currency: str | None
    external_id: str | None
    financial_transaction_id: str | None
    reason: str | None


class MomoGateway(Protocol):
    """What the payment service needs from MTN. MomoClient talks to the real MTN
    API; MomoSimulator (services/momo_simulator.py) fakes it for local development.
    MTN is an EXTERNAL system: the rest of the app only ever sees this interface."""

    def request_to_pay(self, **kw) -> None: ...
    def get_request_to_pay(self, reference_id: str) -> "MomoResult | None": ...
    def transfer(self, **kw) -> None: ...
    def get_transfer(self, reference_id: str) -> "MomoResult | None": ...
    def is_account_active(self, msisdn: str) -> bool: ...


def callback_token(secret: str, kind: Product, reference_id: str) -> str:
    """Per-payment callback signature: a leaked URL only works for that one payment."""
    msg = f"{kind}:{reference_id}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify_callback_token(
    secret: str, kind: Product, reference_id: str, token: str
) -> bool:
    if not secret:
        return False
    return hmac.compare_digest(callback_token(secret, kind, reference_id), token)


def to_momo_amount(amount: Decimal) -> str:
    """RWF has no minor unit. Refuse fractions instead of silently rounding money."""
    if amount <= 0 or amount != amount.to_integral_value():
        raise ValueError("amount must be a positive whole number")
    return str(int(amount))


def _parse_reason(body: dict) -> str | None:
    reason = body.get("reason")
    if isinstance(reason, dict):  # {"code": "...", "message": "..."}
        reason = reason.get("code")
    return str(reason)[:100] if reason else None


class MomoClient:
    def __init__(self, settings: MomoSettings, http: httpx.Client | None = None):
        self.s = settings
        self.http = http or httpx.Client(
            base_url=settings.base_url.rstrip("/"),
            timeout=settings.http_timeout_seconds,
            follow_redirects=False,
        )
        self._tokens: dict[Product, tuple[str, float]] = {}
        self._lock = threading.Lock()

    # ---- credentials -----------------------------------------------------
    def _creds(self, product: Product) -> tuple[str, str, str]:
        if product == "collection":
            return (
                self.s.collection_subscription_key.get_secret_value(),
                self.s.collection_api_user,
                self.s.collection_api_key.get_secret_value(),
            )
        return (
            self.s.disbursement_subscription_key.get_secret_value(),
            self.s.disbursement_api_user,
            self.s.disbursement_api_key.get_secret_value(),
        )

    def _token(self, product: Product) -> str:
        with self._lock:
            cached = self._tokens.get(product)
            if cached and cached[1] > time.monotonic() + 30:
                return cached[0]
            sub_key, user, key = self._creds(product)
            try:
                r = self.http.post(
                    f"/{product}/token/",
                    auth=(user, key),
                    headers={"Ocp-Apim-Subscription-Key": sub_key},
                )
            except httpx.HTTPError as e:
                raise MomoTransient("token request failed") from e
            if r.status_code != 200:
                log.error(
                    "momo token error product=%s status=%s", product, r.status_code
                )
                raise MomoTransient("token request rejected")
            body = r.json()
            token = body["access_token"]
            ttl = int(body.get("expires_in", 3600))
            self._tokens[product] = (token, time.monotonic() + ttl)
            return token

    def _headers(self, product: Product, reference_id: str | None = None) -> dict:
        h = {
            "Authorization": f"Bearer {self._token(product)}",
            "X-Target-Environment": self.s.target_environment,
            "Ocp-Apim-Subscription-Key": self._creds(product)[0],
        }
        if reference_id:
            h["X-Reference-Id"] = reference_id
        return h

    def _callback_url(self, kind: Product, reference_id: str) -> str | None:
        if not self.s.callback_base_url:
            return None
        token = callback_token(
            self.s.callback_secret.get_secret_value(), kind, reference_id
        )
        base = self.s.callback_base_url.rstrip("/")
        return f"{base}/payments/momo/callback/{kind}/{reference_id}/{token}"

    def _post_money(self, product: Product, path: str, ref: str, body: dict) -> None:
        headers = self._headers(product, ref)
        cb = self._callback_url(product, ref)
        if cb:
            headers["X-Callback-Url"] = cb
        try:
            r = self.http.post(path, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise MomoTransient("network error") from e
        if r.status_code == 202:
            return
        if r.status_code == 409:
            return
        if r.status_code >= 500 or r.status_code == 429:
            raise MomoTransient(f"MTN returned {r.status_code}")
        reason = None
        try:
            payload = r.json()
            reason = _parse_reason(payload) or (
                str(payload.get("code"))[:100] if payload.get("code") else None
            )
        except Exception:
            pass
        raise MomoRejected(reason)

    def _get_status(self, product: Product, path: str) -> MomoResult | None:
        try:
            r = self.http.get(path, headers=self._headers(product))
        except httpx.HTTPError as e:
            raise MomoTransient("network error") from e
        if r.status_code == 404:
            return None  # MTN has never heard of this reference
        if r.status_code != 200:
            raise MomoTransient(f"MTN returned {r.status_code}")
        try:
            b = r.json()
            status = b["status"]
            if status not in ("PENDING", "SUCCESSFUL", "FAILED"):
                raise ValueError(status)
            amount = Decimal(str(b["amount"])) if b.get("amount") is not None else None
        except Exception as e:
            raise MomoTransient("unreadable status response") from e
        return MomoResult(
            status=status,
            amount=amount,
            currency=b.get("currency"),
            external_id=b.get("externalId"),
            financial_transaction_id=(
                str(b["financialTransactionId"])[:100]
                if b.get("financialTransactionId")
                else None
            ),
            reason=_parse_reason(b),
        )

    def request_to_pay(
        self,
        *,
        reference_id: str,
        amount: Decimal,
        payer_msisdn: str,
        external_id: str,
        payer_message: str,
        payee_note: str,
    ) -> None:
        self._post_money(
            "collection",
            "/collection/v1_0/requesttopay",
            reference_id,
            {
                "amount": to_momo_amount(amount),
                "currency": self.s.currency,
                "externalId": external_id,
                "payer": {"partyIdType": "MSISDN", "partyId": payer_msisdn},
                "payerMessage": payer_message[:160],
                "payeeNote": payee_note[:160],
            },
        )

    def get_request_to_pay(self, reference_id: str) -> MomoResult | None:
        _check_uuid(reference_id)
        return self._get_status(
            "collection", f"/collection/v1_0/requesttopay/{reference_id}"
        )

    def transfer(
        self,
        *,
        reference_id: str,
        amount: Decimal,
        payee_msisdn: str,
        external_id: str,
        payer_message: str,
        payee_note: str,
    ) -> None:
        self._post_money(
            "disbursement",
            "/disbursement/v1_0/transfer",
            reference_id,
            {
                "amount": to_momo_amount(amount),
                "currency": self.s.currency,
                "externalId": external_id,
                "payee": {"partyIdType": "MSISDN", "partyId": payee_msisdn},
                "payerMessage": payer_message[:160],
                "payeeNote": payee_note[:160],
            },
        )

    def get_transfer(self, reference_id: str) -> MomoResult | None:
        _check_uuid(reference_id)
        return self._get_status(
            "disbursement", f"/disbursement/v1_0/transfer/{reference_id}"
        )

    def is_account_active(self, msisdn: str) -> bool:
        """Is this number a registered, active MoMo account? (Collection product)."""
        try:
            r = self.http.get(
                f"/collection/v1_0/accountholder/msisdn/{msisdn}/active",
                headers=self._headers("collection"),
            )
        except httpx.HTTPError as e:
            raise MomoTransient("network error") from e
        if r.status_code != 200:
            raise MomoTransient(f"MTN returned {r.status_code}")
        return bool(r.json().get("result"))


def _check_uuid(value: str) -> None:

    uuid.UUID(value)
