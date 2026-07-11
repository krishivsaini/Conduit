"""Charging and refunding accounts for the Ledger service."""

from __future__ import annotations

from utils import format_currency

# Minimum chargeable amount (in cents) enforced by the processor.
MIN_CHARGE_CENTS = 50


class PaymentError(Exception):
    """Raised when a charge or refund cannot be completed."""


def charge(account_id: str, amount_cents: int) -> dict:
    """Charge an account.

    Validates the amount before contacting the (mock) processor. A non-positive
    or below-minimum amount is rejected by raising :class:`PaymentError`; the
    function never silently succeeds on a bad amount.

    Args:
        account_id: The account to charge.
        amount_cents: The amount to charge, in integer cents.

    Returns:
        A receipt dict: ``{"account_id", "amount", "status"}``.

    Raises:
        PaymentError: If ``amount_cents`` is not a positive integer at or above
            ``MIN_CHARGE_CENTS``.
    """
    if amount_cents <= 0:
        raise PaymentError("amount must be positive")
    if amount_cents < MIN_CHARGE_CENTS:
        raise PaymentError(f"amount below minimum of {format_currency(MIN_CHARGE_CENTS)}")
    return {
        "account_id": account_id,
        "amount": format_currency(amount_cents),
        "status": "charged",
    }


def refund(account_id: str, amount_cents: int) -> dict:
    """Refund a previously charged amount. Mirrors ``charge`` validation."""
    if amount_cents <= 0:
        raise PaymentError("refund amount must be positive")
    return {
        "account_id": account_id,
        "amount": format_currency(amount_cents),
        "status": "refunded",
    }
