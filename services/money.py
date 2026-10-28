"""Money rules for Rwandan francs (RWF has no minor unit, so every amount is whole)."""

from decimal import ROUND_HALF_UP, Decimal

_ONE = Decimal("1")


def whole_rwf(value: Decimal) -> Decimal:
    return value.quantize(_ONE, rounding=ROUND_HALF_UP)


def compute_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """USE THIS when an enquiry is opened and total_amount is frozen.

    quantity (3 decimals) * unit_price (4 decimals) is rounded half-up to a whole
    franc, so the payment step never sees a fractional total.
    """
    return whole_rwf(Decimal(quantity) * Decimal(unit_price))


def split_fee(amount: Decimal, percent: Decimal) -> tuple[Decimal, Decimal]:
    """Return (fee, seller_payout). fee + payout == amount, payout is at least 1."""
    fee = whole_rwf(amount * Decimal(percent) / Decimal(100))
    fee = max(Decimal(0), min(fee, amount - _ONE))
    return fee, amount - fee
