"""Orders as CSV, for the shop's download button."""


def to_csv(orders: list[tuple[str, int]]) -> str:
    """One `id,cents` row per order, comma-separated, with a header row."""
    rows = ["id,cents"] + [f"{order_id},{cents}" for order_id, cents in orders]
    return "\n".join(rows) + "\n"
