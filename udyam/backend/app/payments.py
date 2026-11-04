"""Razorpay integration (Orders API + Checkout).

Flow: the server creates a Razorpay order for the exact amount of our order, the browser opens Razorpay Checkout,
and the payment is confirmed only on the server, by (a) the HMAC signature Razorpay returns to the browser, after
which we fetch the payment and compare order id, status and amount, and (b) the signed webhook, which covers a
customer who closes the tab right after paying. The browser is never trusted to say "I paid".

Amounts are integer rupees in our database and integer paise (x100) at Razorpay.
"""
from __future__ import annotations

import hashlib
import hmac
import logging

import httpx

from . import config

log = logging.getLogger("udyam.payments")
_API = "https://api.razorpay.com/v1"


class PaymentError(RuntimeError):
    pass


def provider() -> str:
    return "razorpay" if config.RAZORPAY_KEY_ID and config.RAZORPAY_KEY_SECRET else "test"


def _auth() -> tuple[str, str]:
    return config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET


def _call(method: str, path: str, **kw) -> dict:
    try:
        r = httpx.request(method, f"{_API}{path}", auth=_auth(), timeout=20, **kw)
    except httpx.HTTPError as e:
        log.error("razorpay unreachable: %s", type(e).__name__)
        raise PaymentError("The payment service is unreachable. Please try again.")
    if r.status_code >= 400:
        log.error("razorpay %s %s -> %s", method, path, r.status_code)
        raise PaymentError("The payment service rejected the request.")
    return r.json()


def create_order(amount_rupees: int, receipt: str, notes: dict) -> dict:
    return _call("POST", "/orders", json={"amount": int(amount_rupees) * 100, "currency": "INR", "receipt": receipt,
                                           "payment_capture": 1, "notes": notes})


def fetch_payment(payment_id: str) -> dict:
    return _call("GET", f"/payments/{payment_id}")


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def verify_checkout_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Razorpay signs `order_id|payment_id` with the key secret."""
    expected = hmac.new(config.RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(),
                        hashlib.sha256).hexdigest()
    return _eq(expected, signature or "")


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """Webhooks are signed over the raw request body with the webhook secret (not the API secret)."""
    if not config.RAZORPAY_WEBHOOK_SECRET:
        return False
    expected = hmac.new(config.RAZORPAY_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return _eq(expected, signature or "")


def payment_matches(payment: dict, razorpay_order_id: str, amount_rupees: int) -> tuple[bool, str]:
    """Server-side check of a fetched payment against what we expect to be paid."""
    if payment.get("order_id") != razorpay_order_id:
        return False, "payment belongs to a different order"
    if int(payment.get("amount", -1)) != int(amount_rupees) * 100:
        return False, "amount does not match"
    if payment.get("currency") != "INR":
        return False, "currency does not match"
    if payment.get("status") not in ("captured", "authorized"):
        return False, f"payment status is {payment.get('status')}"
    return True, ""
