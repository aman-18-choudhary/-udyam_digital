"""Full journey through the HTTP API (auth off, temp SQLite, Gemini off, demo mode on for sample documents)."""
import time

import pytest


@pytest.fixture
def client(app_factory):
    return app_factory(auth=False)[0]


def journey(client):
    from app.data import gstin_registry
    r = client.post("/api/advisor/start", json={"language": "en"}).json()
    sid = r["session_id"]
    for m in ("dental clinic", "5", "Nagpur", "Business broadband"):
        r = client.post("/api/advisor/message", json={"session_id": sid, "text": m}).json()
    g = next(g for g, row in gstin_registry().items() if row["status"] == "Active")
    r = client.post("/api/advisor/message", json={"session_id": sid, "text": g}).json()
    assert r["done"]
    return sid, r["recommendation"]


def items_of(rec):
    return [{"product_id": i["product_id"], "qty": i["qty"], "included": i["included"]} for i in rec["items"]]


def consent(client, sid):
    return client.post("/api/consent", json={"session_id": sid, "accept": True, "notice_version": "2026-07-v1"})


def test_consent_is_required_before_kyc(client):
    sid, _ = journey(client)
    assert client.post("/api/kyc/cases", json={"session_id": sid}).status_code == 403


def test_full_journey_to_activation_with_demo_timer(client):
    sid, rec = journey(client)
    assert consent(client, sid).status_code == 200
    case = client.post("/api/kyc/cases", json={"session_id": sid}).json()
    r = client.post(f"/api/kyc/cases/{case['id']}/specimen", json={"applicant": "K03"})
    assert r.status_code == 200, r.text
    v = client.post(f"/api/kyc/cases/{case['id']}/verify").json()
    assert v["status"] == "verified"
    assert "XUIXG0767D1ZP" not in str(v)  # identifiers stay masked

    items = items_of(rec)
    q = client.post("/api/quote", json={"session_id": sid, "items": items, "term": 12, "kyc_case_id": case["id"]}).json()
    assert q["ok"]
    o = client.post("/api/orders", json={"session_id": sid, "kyc_case_id": case["id"], "items": items, "term": 12}).json()
    assert o["status"] == "PAYMENT_PENDING"
    bad = client.post(f"/api/orders/{o['id']}/pay", json={"method": "upi", "simulate_failure": True}).json()
    assert bad["status"] == "PAYMENT_FAILED"
    client.post(f"/api/orders/{o['id']}/pay", json={"method": "upi"})
    for _ in range(40):
        time.sleep(0.2)
        if client.get(f"/api/orders/{o['id']}").json()["status"] == "ACTIVATED":
            break
    final = client.get(f"/api/orders/{o['id']}").json()
    assert final["status"] == "ACTIVATED"
    assert [e["status"] for e in final["events"]][-1] == "ACTIVATED"


def test_rejected_documents_block_the_order_and_withdrawal_deletes_them(client, tmp_path):
    sid, rec = journey(client)
    consent(client, sid)
    case = client.post("/api/kyc/cases", json={"session_id": sid}).json()
    client.post(f"/api/kyc/cases/{case['id']}/specimen", json={"applicant": "K11"})
    stored = list((tmp_path / "uploads").rglob("*.bin"))
    assert stored, "documents should be stored encrypted"
    assert b"Specimen" not in stored[0].read_bytes()  # ciphertext, not an image
    v = client.post(f"/api/kyc/cases/{case['id']}/verify").json()
    assert v["status"] == "action_required"
    items = [{"product_id": "P02", "qty": 1, "included": True}]
    assert client.post("/api/orders", json={"session_id": sid, "kyc_case_id": case["id"], "items": items}).status_code == 409
    d = client.delete(f"/api/consent/{sid}").json()
    assert d["documents_deleted"] >= 1
    assert client.get(f"/api/kyc/cases/{case['id']}").status_code == 404
    assert not list((tmp_path / "uploads").rglob("*.bin"))


def test_server_recomputes_price_and_blocks_invalid_bundle(client):
    sid, _ = journey(client)
    r = client.post("/api/quote", json={"session_id": sid, "term": 12,
                                        "items": [{"product_id": "P23", "qty": 2, "included": True}]}).json()
    assert not r["ok"] and r["problems"][0]["code"] == "dependency"


def test_gst_products_need_gst_proof_in_the_documents_not_just_a_typed_gstin(client):
    sid, rec = journey(client)  # typed an Active GSTIN, so the advisor offered GST products
    consent(client, sid)
    case = client.post("/api/kyc/cases", json={"session_id": sid}).json()
    client.post(f"/api/kyc/cases/{case['id']}/specimen", json={"applicant": "K01"})  # cancelled GST
    client.post(f"/api/kyc/cases/{case['id']}/verify")
    items = [{"product_id": "P02", "qty": 1, "included": True}, {"product_id": "P15", "qty": 1, "included": True}]
    q = client.post("/api/quote", json={"session_id": sid, "items": items, "term": 12, "kyc_case_id": case["id"]}).json()
    assert not q["ok"] and "GSTIN" in q["problems"][0]["message"]


def test_lookup_masks_identifier(client):
    from app.data import gstin_registry
    g = next(iter(gstin_registry()))
    r = client.post("/api/kyc/lookup", json={"gstin": g}).json()
    assert r["gstin"]["found"] and g not in str(r)


def test_demo_helpers_are_off_when_demo_mode_is_off(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEMO_MODE", False)
    assert client.get("/api/kyc/specimens").status_code == 404
    assert client.get("/api/config").json()["demo"] is False


def test_health_checks_the_database(client):
    h = client.get("/api/health")
    assert h.status_code == 200 and h.json()["db"] == "up"
