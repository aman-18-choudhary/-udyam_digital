"""Test environment. These must be set before any `app` module is imported."""
import importlib
import os
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault("UDYAM_TODAY", "2026-07-15")   # the case specimens are dated against this day
os.environ["GEMINI_API_KEY"] = ""                      # tests never call the network
os.environ["CLERK_ISSUER"] = ""                        # auth is switched on per test below
# The suite must never touch real services, even when .env holds real keys.
os.environ["DATABASE_URL"] = "sqlite://"
for _k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "CLERK_AUTHORIZED_PARTIES", "STORAGE_BACKEND"):
    os.environ[_k] = ""
os.environ["DEMO_MODE"] = "true"
for _k in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
    os.environ[_k] = ""
os.environ["DEMO_STEP_SECONDS"] = "0.2"
os.environ["KYC_ENC_KEY"] = "8q9Xn3YlYy3m0cQ1m9Qw9m2Yk3o1l0G6m3m7nWZpQ4o="

ISSUER = "https://test.clerk.accounts.dev"
_MODULES = ["app.config", "app.db", "app.storage", "app.auth", "app.payments", "app.orders", "app.llm", "app.advisor", "app.main"]


def _reload_app():
    for m in _MODULES:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
        else:
            importlib.import_module(m)
    import app.storage
    app.storage.get_storage.cache_clear()
    return sys.modules["app.main"]


@pytest.fixture
def app_factory(tmp_path, monkeypatch):
    """Returns build(auth=False) -> (TestClient, main module). Fresh database and upload dir per call."""
    from fastapi.testclient import TestClient
    clients = []

    def build(auth: bool = False, razorpay: bool = False):
        pg = os.environ.get("TEST_DATABASE_URL")  # run the suite against real Postgres: TEST_DATABASE_URL=...
        monkeypatch.setenv("DATABASE_URL", pg or f"sqlite:///{tmp_path / 'test.db'}")
        monkeypatch.setenv("UDYAM_UPLOAD_DIR", str(tmp_path / "uploads"))
        monkeypatch.setenv("CLERK_ISSUER", ISSUER if auth else "")
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_key" if razorpay else "")
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "key_secret_123" if razorpay else "")
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_456" if razorpay else "")
        main = _reload_app()
        if pg:
            from app.db import Base, engine
            Base.metadata.drop_all(engine)
            Base.metadata.create_all(engine)
        from app import llm
        llm.available = lambda: False
        c = TestClient(main.app)
        c.__enter__()
        clients.append(c)
        return c, main

    yield build
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def clerk():
    """RSA key pair plus a token factory, so auth tests run without contacting Clerk."""
    import time
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    stub = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key()))

    def token(sub: str, role: str | None = None, exp_in: int = 300, issuer: str = ISSUER) -> str:
        now = int(time.time())
        claims = {"sub": sub, "iss": issuer, "iat": now, "nbf": now, "exp": now + exp_in}
        if role:
            claims["metadata"] = {"role": role}
        return jwt.encode(claims, pem, algorithm="RS256")

    import app.auth  # noqa
    return SimpleNamespace(token=token, stub=stub, headers=lambda *a, **k: {"authorization": f"Bearer {token(*a, **k)}"})
