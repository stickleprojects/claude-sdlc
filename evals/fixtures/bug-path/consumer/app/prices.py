"""Prices for the checkout page. Amounts are whole cents."""


def format_price(cents: int) -> str:
    """The price as the checkout page shows it, in dollars."""
    return f"${cents / 100}"
