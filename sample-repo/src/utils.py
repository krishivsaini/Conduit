"""Shared helpers for the Ledger service."""

from __future__ import annotations

CURRENCY_SYMBOL = "$"


def format_currency(amount_cents: int) -> str:
    """Format an integer amount of cents as a currency string.

    Example:
        >>> format_currency(1050)
        '$10.50'
    """
    return f"{CURRENCY_SYMBOL}{amount_cents / 100:.2f}"


def redact(secret: str) -> str:
    """Redact a secret, keeping only its last two characters visible."""
    if len(secret) <= 2:
        return "*" * len(secret)
    return "*" * (len(secret) - 2) + secret[-2:]
