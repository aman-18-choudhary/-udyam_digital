"""Razorpay: server-side order, signature and amount checks, webhook, idempotency. Razorpay's API is mocked."""
import hashlib
import hmac
import json

import httpx
import pytest

KEY_SECRET, WEBHOOK_SECRET = "key_secret_123", "whsec_456"


def sign(order_id, payment_id, secret=KEY_SECRET):
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


class FakeRazorpay:
    """Stands in for api.razorpay.com. `payments` maps payment id -> payment entity."""

    def __init__(self):
        self.orders_created = 0
        self.payments = {}

    def request(self, method, url, **kw):
        path = url.split("/v1", 1)[1]
        if method == "POST" and path == "/orders":
            self.orders_created += 1
            body = kw["json"]
            data = {"id": f"order_RZ{self.orders_created}", "amount": body["amount"], "currency": "INR"}
            return httpx.Response(200, json=data, request=httpx.Request(method, url))
        if method == "GET" and path.startswith("/payments/"):
            pid = path.rsplit("/", 1)[1]
            if pid in self.payments:
                return httpx.Response(200, json=self.payments[pid], request=httpx.Request(method, url))
        return httpx.Response(404, json={}, request=httpx.Request(method, url))


@pytest.fixture
def rz(app_factory, monkeypatch):
    client, main = app_factory(razorpay=True)
    fake = FakeRazorpay()
    import app.payments
    monkeypatch.setattr(app.payments.httpx, "request", fake.request)
    return client, main, fake


def new_order(client, applicant="K03"):
    r = client.post("/api/advisor/start", json={"language": "en"}).json()
    sid = r["session_id"]
    for m in ("dental clinic", "5", "Nagpur", "Business broadband", "no"):
        r = client.post("/api/advisor/message", json={"session_id": sid, "text": m}).json()
    items = [{"product_id": i["product_id"], "qty": i["qty"], "included": i["included"]} for i in r["recommendation"]["items"]]
    client.post("/api/consent", json={"session_id": sid, "accept": True, "notice_version": "2026-07-v1"})
    case = client.post("/api/kyc/cases", json={"session_id": sid}).json()
    client.post(f"/api/kyc/cases/{case['id']}/specimen", json={"applicant": applicant})
    client.post(f"/api/kyc/cases/{case['id']}/verify")
    return client.post("/api/orders", json={"session_id": sid, "kyc_case_id": case["id"], "items": items}).json()


def payment(order, pid="pay_1", rzp_order="order_RZ1", amount=None, status="captured"):
    return {"id": pid, "order_id": rzp_order, "amount": (amount if amount is not None else order["first_payment"] * 100),
            "currency": "INR", "status": status, "method": "upi"}


def webhook(client, body: dict, secret=WEBHOOK_SECRET):
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/api/webhooks/razorpay", content=raw, headers={"x-razorpay-signature": sig, "content-type": "application/json"})


def confirmed(client, oid):
    o = client.get(f"/api/orders/{oid}").json()
    return o["status"], [e["status"] for e in o["events"]].count("PAYMENT_CONFIRMED")


def test_config_exposes_only_the_public_key(rz):
    client, _, _ = rz
    cfg = client.get("/api/config").json()
    assert cfg["payments"] == {"provider": "razorpay", "key_id": "rzp_test_key"}
    assert KEY_SECRET not in json.dumps(cfg) and WEBHOOK_SECRET not in json.dumps(cfg)


def test_test_mode_payment_is_disabled_when_a_gateway_is_configured(rz):
    client, _, _ = rz
    o = new_order(client)
    r = client.post(f"/api/orders/{o['id']}/pay", json={"method": "upi"})
    assert r.status_code == 409
    assert client.get(f"/api/orders/{o['id']}").json()["status"] == "PAYMENT_PENDING"


def test_intent_uses_the_servers_amount_and_is_reused_on_retry(rz):
    client, _, fake = rz
    o = new_order(client)
    a = client.post(f"/api/orders/{o['id']}/payment-intent").json()
    b = client.post(f"/api/orders/{o['id']}/payment-intent").json()
    assert a["amount_paise"] == o["first_payment"] * 100 and a["key_id"] == "rzp_test_key"
    assert a["razorpay_order_id"] == b["razorpay_order_id"] and fake.orders_created == 1


def test_valid_payment_confirms_the_order_once(rz):
    client, _, fake = rz
    o = new_order(client)
    intent = client.post(f"/api/orders/{o['id']}/payment-intent").json()
    fake.payments["pay_1"] = payment(o)
    body = {"razorpay_order_id": intent["razorpay_order_id"], "razorpay_payment_id": "pay_1",
            "razorpay_signature": sign(intent["razorpay_order_id"], "pay_1")}
    assert client.post(f"/api/orders/{o['id']}/verify-payment", json=body).status_code == 200
    assert client.post(f"/api/orders/{o['id']}/verify-payment", json=body).status_code == 200  # replay is harmless
    assert confirmed(client, o["id"]) == ("PAYMENT_CONFIRMED", 1)


def test_forged_signature_is_rejected(rz):
    client, _, fake = rz
    o = new_order(client)
    intent = client.post(f"/api/orders/{o['id']}/payment-intent").json()
    fake.payments["pay_1"] = payment(o)
    body = {"razorpay_order_id": intent["razorpay_order_id"], "razorpay_payment_id": "pay_1",
            "razorpay_signature": sign(intent["razorpay_order_id"], "pay_1", secret="attacker_guess")}
    assert client.post(f"/api/orders/{o['id']}/verify-payment", json=body).status_code == 400
    assert confirmed(client, o["id"]) == ("PAYMENT_PENDING", 0)


def test_underpayment_with_a_valid_signature_is_rejected(rz):
    client, _, fake = rz
    o = new_order(client)
    intent = client.post(f"/api/orders/{o['id']}/payment-intent").json()
    fake.payments["pay_1"] = payment(o, amount=100)  # paid Rs 1
    body = {"razorpay_order_id": intent["razorpay_order_id"], "razorpay_payment_id": "pay_1",
            "razorpay_signature": sign(intent["razorpay_order_id"], "pay_1")}
    assert client.post(f"/api/orders/{o['id']}/verify-payment", json=body).status_code == 400
    assert confirmed(client, o["id"]) == ("PAYMENT_PENDING", 0)


def test_authorized_but_uncaptured_or_failed_payment_does_not_confirm(rz):
    client, _, fake = rz
    o = new_order(client)
    intent = client.post(f"/api/orders/{o['id']}/payment-intent").json()
    fake.payments["pay_1"] = payment(o, status="failed")
    body = {"razorpay_order_id": intent["razorpay_order_id"], "razorpay_payment_id": "pay_1",
            "razorpay_signature": sign(intent["razorpay_order_id"], "pay_1")}
    assert client.post(f"/api/orders/{o['id']}/verify-payment", json=body).status_code == 400


def test_a_payment_for_another_razorpay_order_cannot_be_used(rz):
    client, _, fake = rz
    o = new_order(client)
    client.post(f"/api/orders/{o['id']}/payment-intent")
    body = {"razorpay_order_id": "order_SOMEONE_ELSE", "razorpay_payment_id": "pay_9",
            "razorpay_signature": sign("order_SOMEONE_ELSE", "pay_9")}
    assert client.post(f"/api/orders/{o['id']}/verify-payment", json=body).status_code == 400


def test_one_payment_cannot_pay_two_orders(rz):
    client, _, fake = rz
    o1, o2 = new_order(client), new_order(client)
    i1 = client.post(f"/api/orders/{o1['id']}/payment-intent").json()
    i2 = client.post(f"/api/orders/{o2['id']}/payment-intent").json()
    fake.payments["pay_1"] = payment(o1, rzp_order=i1["razorpay_order_id"])
    b1 = {"razorpay_order_id": i1["razorpay_order_id"], "razorpay_payment_id": "pay_1", "razorpay_signature": sign(i1["razorpay_order_id"], "pay_1")}
    assert client.post(f"/api/orders/{o1['id']}/verify-payment", json=b1).status_code == 200
    fake.payments["pay_1"] = payment(o2, rzp_order=i2["razorpay_order_id"])  # same payment id replayed on order 2
    b2 = {"razorpay_order_id": i2["razorpay_order_id"], "razorpay_payment_id": "pay_1", "razorpay_signature": sign(i2["razorpay_order_id"], "pay_1")}
    assert client.post(f"/api/orders/{o2['id']}/verify-payment", json=b2).status_code == 409
    assert confirmed(client, o2["id"])[0] == "PAYMENT_PENDING"


def test_webhook_confirms_when_the_customer_closed_the_tab(rz):
    client, _, fake = rz
    o = new_order(client)
    intent = client.post(f"/api/orders/{o['id']}/payment-intent").json()
    ev = {"event": "payment.captured", "payload": {"payment": {"entity": payment(o, "pay_7", intent["razorpay_order_id"])}}}
    assert webhook(client, ev).status_code == 200
    assert webhook(client, ev).status_code == 200  # Razorpay retries are harmless
    assert confirmed(client, o["id"]) == ("PAYMENT_CONFIRMED", 1)


def test_webhook_rejects_bad_signature_and_wrong_amount(rz):
    client, _, fake = rz
    o = new_order(client)
    intent = client.post(f"/api/orders/{o['id']}/payment-intent").json()
    ev = {"event": "payment.captured", "payload": {"payment": {"entity": payment(o, "pay_7", intent["razorpay_order_id"])}}}
    assert webhook(client, ev, secret="wrong").status_code == 400
    cheap = {"event": "payment.captured", "payload": {"payment": {"entity": payment(o, "pay_8", intent["razorpay_order_id"], amount=100)}}}
    assert webhook(client, cheap).status_code == 200
    assert confirmed(client, o["id"]) == ("PAYMENT_PENDING", 0)


def test_failed_payment_event_never_downgrades_a_paid_order(rz):
    client, _, fake = rz
    o = new_order(client)
    intent = client.post(f"/api/orders/{o['id']}/payment-intent").json()
    failed = {"event": "payment.failed", "payload": {"payment": {"entity": payment(o, "pay_f", intent["razorpay_order_id"], status="failed")}}}
    webhook(client, failed)
    assert client.get(f"/api/orders/{o['id']}").json()["status"] == "PAYMENT_FAILED"
    ok = {"event": "payment.captured", "payload": {"payment": {"entity": payment(o, "pay_ok", intent["razorpay_order_id"])}}}
    webhook(client, ok)
    assert confirmed(client, o["id"]) == ("PAYMENT_CONFIRMED", 1)
    webhook(client, failed)
    assert client.get(f"/api/orders/{o['id']}").json()["status"] == "PAYMENT_CONFIRMED"


def test_online_flow_is_off_without_keys(app_factory):
    client, _ = app_factory()
    o = new_order(client)
    assert client.post(f"/api/orders/{o['id']}/payment-intent").status_code == 409
    assert client.post("/api/webhooks/razorpay", content=b"{}", headers={"x-razorpay-signature": "x"}).status_code == 400
