import time
import uuid
from decimal import Decimal
from typing import Callable

from core.payment_config import MomoSettings
from services.momo import MomoResult, to_momo_amount


class MomoSimulator:
    def __init__(
        self, settings: MomoSettings, clock: Callable[[], float] = time.monotonic
    ):
        self.s = settings
        self.clock = clock
        self._collections: dict[str, dict] = {}
        self._transfers: dict[str, dict] = {}

    # ---- collection ---------------------------------------------------------
    def request_to_pay(
        self,
        *,
        reference_id,
        amount,
        payer_msisdn,
        external_id,
        payer_message,
        payee_note,
    ) -> None:
        to_momo_amount(amount)
        self._collections.setdefault(
            reference_id,
            dict(
                amount=amount,
                msisdn=payer_msisdn,
                external_id=external_id,
                at=self.clock(),
            ),
        )

    def get_request_to_pay(self, reference_id: str) -> MomoResult | None:
        rec = self._collections.get(reference_id)
        if rec is None:
            return None
        phone = rec["msisdn"]
        if phone.endswith("000"):
            return self._result("FAILED", rec, "APPROVAL_REJECTED")
        if phone.endswith("111"):
            return self._result("PENDING", rec)
        return self._result(self._by_time(rec), rec)

    # ---- disbursement -------------------------------------------------------
    def transfer(
        self,
        *,
        reference_id,
        amount,
        payee_msisdn,
        external_id,
        payer_message,
        payee_note,
    ) -> None:
        to_momo_amount(amount)
        self._transfers.setdefault(
            reference_id,
            dict(
                amount=amount,
                msisdn=payee_msisdn,
                external_id=external_id,
                at=self.clock(),
            ),
        )

    def get_transfer(self, reference_id: str) -> MomoResult | None:
        rec = self._transfers.get(reference_id)
        if rec is None:
            return None
        if rec["msisdn"].endswith("000"):
            return self._result("FAILED", rec, "PAYEE_NOT_FOUND")
        return self._result(self._by_time(rec), rec)

    def is_account_active(self, msisdn: str) -> bool:
        return not msisdn.endswith("000")

    # ---- helpers ------------------------------------------------------------
    def _by_time(self, rec: dict) -> str:
        waited = self.clock() - rec["at"]
        return "SUCCESSFUL" if waited >= self.s.simulator_delay_seconds else "PENDING"

    def _result(self, status: str, rec: dict, reason: str | None = None) -> MomoResult:
        return MomoResult(
            status=status,  # type: ignore[arg-type]
            amount=Decimal(rec["amount"]),
            currency=self.s.currency,
            external_id=rec["external_id"],
            financial_transaction_id=str(uuid.uuid4())[:12]
            if status == "SUCCESSFUL"
            else None,
            reason=reason,
        )
