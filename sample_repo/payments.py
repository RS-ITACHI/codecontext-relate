"""Payment processing & idempotency module for sample microservice."""


def verify_idempotency_key(key: str, seen_keys: set[str]) -> bool:
    """Ensure duplicate webhook/checkout retries never double-charge a customer."""
    if not key or key in seen_keys:
        return False
    seen_keys.add(key)
    return True


def calculate_settlement_fee(amount_cents: int) -> int:
    """Compute platform fee in integer cents (never floats)."""
    return (amount_cents * 29) // 1000 + 30


def process_checkout(order_id: str, amount_cents: int, idempotency_key: str, seen_keys: set[str]) -> dict:
    """Execute a checkout charge after validating idempotency and fee calculation."""
    if not verify_idempotency_key(idempotency_key, seen_keys):
        return {"status": "duplicate_ignored", "order_id": order_id}
    fee = calculate_settlement_fee(amount_cents)
    return {"status": "charged", "order_id": order_id, "amount_cents": amount_cents, "fee_cents": fee}
