"""Supabase Storage client: correct URLs, auth headers and error handling, with HTTP mocked."""
import httpx
import pytest

from app import storage


def make(monkeypatch, status=200, body=b"cipher"):
    calls = []

    def fake(method):
        def _f(url, **kw):
            calls.append((method, url, kw))
            return httpx.Response(status, content=body, request=httpx.Request(method, url))
        return _f

    monkeypatch.setattr(storage.httpx, "post", fake("POST"))
    monkeypatch.setattr(storage.httpx, "get", fake("GET"))
    monkeypatch.setattr(storage.httpx, "request", lambda m, url, **kw: fake(m)(url, **kw))
    return storage.SupabaseStorage("https://proj.supabase.co", "SERVICE_KEY", "kyc-documents"), calls


def test_upload_download_delete_use_private_bucket_and_server_key(monkeypatch):
    s, calls = make(monkeypatch)
    s.put("k_1/gst.bin", b"cipher")
    assert s.get("k_1/gst.bin") == b"cipher"
    s.delete(["k_1/gst.bin", "k_1/id.bin"])
    (m1, u1, k1), (m2, u2, _), (m3, u3, k3) = calls
    assert (m1, u1) == ("POST", "https://proj.supabase.co/storage/v1/object/kyc-documents/k_1/gst.bin")
    assert k1["headers"]["authorization"] == "Bearer SERVICE_KEY" and k1["headers"]["x-upsert"] == "true"
    assert (m2, u2) == ("GET", "https://proj.supabase.co/storage/v1/object/kyc-documents/k_1/gst.bin")
    assert (m3, u3) == ("DELETE", "https://proj.supabase.co/storage/v1/object/kyc-documents")
    assert k3["json"] == {"prefixes": ["k_1/gst.bin", "k_1/id.bin"]}
    assert "public" not in u1  # never the public URL form


def test_storage_errors_surface_as_storage_error(monkeypatch):
    s, _ = make(monkeypatch, status=500)
    with pytest.raises(storage.StorageError):
        s.put("a/b.bin", b"x")


def test_local_storage_roundtrip_and_cleanup(tmp_path):
    s = storage.LocalStorage(tmp_path)
    s.put("c1/id.bin", b"abc")
    assert s.get("c1/id.bin") == b"abc"
    s.delete(["c1/id.bin"])
    assert not (tmp_path / "c1").exists()
    with pytest.raises(storage.StorageError):
        s.get("c1/id.bin")
