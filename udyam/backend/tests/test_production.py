"""Authentication, ownership, roles and the staff workflow, with Clerk tokens signed by a local test key."""
import pytest


@pytest.fixture
def env(app_factory, clerk, monkeypatch):
    client, main = app_factory(auth=True)
    import app.auth
    monkeypatch.setattr(app.auth, "_jwks", lambda: clerk.stub)
    return client, main, clerk


def start(client, headers):
    r = client.post("/api/advisor/start", json={"language": "en"}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def test_requests_without_a_token_are_rejected(env):
    client, _, _ = env
    assert client.post("/api/advisor/start", json={}).status_code == 401
    assert client.get("/api/health").status_code == 200           # public
    assert client.get("/api/consent/notice").status_code == 200   # public


def test_forged_expired_and_wrong_issuer_tokens_are_rejected(env):
    client, _, clerk = env
    h = {"authorization": "Bearer not.a.jwt"}
    assert client.get("/api/me", headers=h).status_code == 401
    assert client.get("/api/me", headers=clerk.headers("u1", exp_in=-120)).status_code == 401
    assert client.get("/api/me", headers=clerk.headers("u1", issuer="https://evil.example")).status_code == 401
    assert client.get("/api/me", headers=clerk.headers("u1")).json()["role"] == "customer"


def test_customers_cannot_see_each_others_sessions_or_orders(env):
    client, _, clerk = env
    a, b = clerk.headers("user_a"), clerk.headers("user_b")
    sid = start(client, a)
    assert client.post("/api/advisor/message", json={"session_id": sid, "text": "clinic"}, headers=b).status_code == 404
    assert client.get(f"/api/advisor/session/{sid}", headers=b).status_code == 404
    assert client.post("/api/consent", json={"session_id": sid, "accept": True, "notice_version": "2026-07-v1"},
                       headers=b).status_code == 404
    assert client.post("/api/advisor/message", json={"session_id": sid, "text": "clinic"}, headers=a).status_code == 200


def test_staff_endpoints_need_a_staff_role(env):
    client, _, clerk = env
    assert client.get("/api/backoffice/funnel", headers=clerk.headers("c1")).status_code == 403
    assert client.get("/api/backoffice/funnel", headers=clerk.headers("s1", role="sales")).status_code == 200
    assert client.get("/api/ops/reviews", headers=clerk.headers("c1")).status_code == 403
    # sales can read the queue but only ops (or admin) can decide or advance
    assert client.get("/api/ops/reviews", headers=clerk.headers("s1", role="sales")).status_code == 200
    assert client.post("/api/ops/reviews/k_x/decision", json={"approve": True},
                       headers=clerk.headers("s1", role="sales")).status_code == 403
    assert client.post("/api/admin/purge", headers=clerk.headers("c1")).status_code == 403
    assert client.post("/api/admin/purge", headers=clerk.headers("o1", role="ops")).status_code == 200


def test_a_role_claim_the_customer_invents_is_ignored_unless_it_is_in_the_signed_token(env):
    client, _, clerk = env
    h = clerk.headers("c2")
    h["x-role"] = "admin"
    assert client.get("/api/backoffice/funnel", headers=h).status_code == 403


def _paid_order(client, clerk, applicant):
    """Customer journey up to a paid order for the given sample applicant. Returns (order_id, headers)."""
    from app.data import gstin_registry
    cust = clerk.headers("cust_1")
    sid = start(client, cust)
    for m in ("dental clinic", "5", "Nagpur", "Business broadband", "no"):
        r = client.post("/api/advisor/message", json={"session_id": sid, "text": m}, headers=cust).json()
    items = [{"product_id": i["product_id"], "qty": i["qty"], "included": i["included"]}
             for i in r["recommendation"]["items"]]
    client.post("/api/consent", json={"session_id": sid, "accept": True, "notice_version": "2026-07-v1"}, headers=cust)
    case = client.post("/api/kyc/cases", json={"session_id": sid}, headers=cust).json()
    assert client.post(f"/api/kyc/cases/{case['id']}/specimen", json={"applicant": applicant}, headers=cust).status_code == 200
    v = client.post(f"/api/kyc/cases/{case['id']}/verify", headers=cust).json()
    o = client.post("/api/orders", json={"session_id": sid, "kyc_case_id": case["id"], "items": items}, headers=cust)
    assert o.status_code == 200, o.text
    oid = o.json()["id"]
    return oid, case["id"], v["status"], cust


def test_ops_workflow_without_demo_timer_and_review_gate(env, monkeypatch):
    client, main, clerk = env
    oid, cid, kyc_status, cust = _paid_order(client, clerk, "K08")  # signatory is "Office admin" -> manual review
    assert kyc_status == "review"
    from app import config
    monkeypatch.setattr(config, "DEMO_MODE", False)                  # real behaviour: nothing moves by itself
    paid = client.post(f"/api/orders/{oid}/pay", json={"method": "upi"}, headers=cust).json()
    assert paid["status"] == "KYC_REVIEW"
    ops = clerk.headers("ops_1", role="ops")

    # another customer cannot read this order; staff can
    assert client.get(f"/api/orders/{oid}", headers=clerk.headers("cust_2")).status_code == 404
    assert client.get(f"/api/orders/{oid}", headers=ops).status_code == 200

    # the pipeline is blocked on the pending manual review
    r = client.post(f"/api/ops/orders/{oid}/advance", headers=ops)
    assert r.status_code == 409 and "review" in r.json()["detail"].lower()

    # reviewer looks at a document (audited), then approves
    queue = client.get("/api/ops/reviews", headers=ops).json()
    assert any(q["id"] == cid for q in queue)
    img = client.get(f"/api/ops/reviews/{cid}/documents/id", headers=ops)
    assert img.status_code == 200 and img.headers["content-type"].startswith("image/")
    assert client.post(f"/api/ops/reviews/{cid}/decision", json={"approve": True}, headers=ops).json()["status"] == "verified"

    states = []
    for _ in range(6):
        r = client.post(f"/api/ops/orders/{oid}/advance", headers=ops)
        if r.status_code != 200:
            break
        states.append(r.json()["status"])
    assert states == ["KYC_VERIFIED", "INSTALL_SCHEDULED", "INSTALLING", "ACTIVATED"]
    assert client.post(f"/api/ops/orders/{oid}/advance", headers=ops).status_code == 409
    mine = client.get("/api/my/orders", headers=cust).json()
    assert [m["id"] for m in mine] == [oid] and mine[0]["status"] == "ACTIVATED"


def test_customer_cannot_advance_their_own_order(env, monkeypatch):
    client, _, clerk = env
    oid, _, _, cust = _paid_order(client, clerk, "K03")
    from app import config
    monkeypatch.setattr(config, "DEMO_MODE", False)
    client.post(f"/api/orders/{oid}/pay", json={"method": "upi"}, headers=cust)
    assert client.post(f"/api/ops/orders/{oid}/advance", headers=cust).status_code == 403
    assert client.get(f"/api/orders/{oid}", headers=cust).json()["status"] == "PAYMENT_CONFIRMED"
