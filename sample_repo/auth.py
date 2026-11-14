"""Authentication & webhook signature verification."""

import hmac
import hashlib
from sample_repo.payments import process_checkout


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 verification for payment webhooks."""
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def handle_payment_webhook(payload: bytes, signature: str, secret: str, order_id: str, amount_cents: int, idem_key: str, seen: set[str]) -> dict:
    """Verify webhook authenticity before dispatching checkout settlement."""
    if not verify_webhook_signature(payload, signature, secret):
        raise PermissionError("Invalid webhook signature")
    return process_checkout(order_id, amount_cents, idem_key, seen)
