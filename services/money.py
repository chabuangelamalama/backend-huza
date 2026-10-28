from decimal import ROUND_HALF_UP, Decimal

_ONE = Decimal("1")


def whole_kes(value: Decimal) -> Decimal:
    """Rounds the KES transaction values half-up to a whole shilling,

    ensuring absolute integer alignment across M-Pesa API transaction steps.
    """
    return value.quantize(_ONE, rounding=ROUND_HALF_UP)


def compute_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """USE THIS when an enquiry is opened and total_amount is frozen.

    quantity (3 decimals) * unit_price (4 decimals) is rounded half-up to a whole
    shilling, so the payment step never sees a fractional total.
    """
    return whole_kes(Decimal(quantity) * Decimal(unit_price))


def split_fee(amount: Decimal, percent: Decimal) -> tuple[Decimal, Decimal]:
    """Return (fee, seller_payout). fee + payout == amount, payout is at least 1."""
    fee = whole_kes(amount * Decimal(percent) / Decimal(100))
    fee = max(Decimal(0), min(fee, amount - _ONE))
    return fee, amount - fee
