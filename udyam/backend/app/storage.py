"""Document storage. Content is always Fernet-encrypted before it reaches this layer, so the
backend (local disk or a Supabase Storage private bucket) only ever holds ciphertext."""
from __future__ import annotations

import logging
import shutil
from functools import lru_cache
from pathlib import Path

import httpx

from . import config

log = logging.getLogger("udyam.storage")


class StorageError(RuntimeError):
    pass


class LocalStorage:
    name = "local"

    def __init__(self, root: Path):
        self.root = root

    def put(self, key: str, data: bytes) -> None:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        try:
            return (self.root / key).read_bytes()
        except FileNotFoundError:
            raise StorageError("document not found")

    def delete(self, keys: list[str]) -> None:
        for k in keys:
            (self.root / k).unlink(missing_ok=True)
        for d in {(self.root / k).parent for k in keys}:
            if d.exists() and not any(d.iterdir()):
                shutil.rmtree(d, ignore_errors=True)


class SupabaseStorage:
    """Private bucket accessed server side with the service-role key (never exposed to the browser)."""
    name = "supabase"

    def __init__(self, url: str, service_key: str, bucket: str):
        self.base = f"{url}/storage/v1"
        self.bucket = bucket
        self.headers = {"apikey": service_key, "authorization": f"Bearer {service_key}"}

    def _check(self, r: httpx.Response, what: str) -> None:
        if r.status_code >= 400:
            log.error("supabase storage %s failed: %s", what, r.status_code)
            raise StorageError(f"storage {what} failed ({r.status_code})")

    def put(self, key: str, data: bytes) -> None:
        r = httpx.post(f"{self.base}/object/{self.bucket}/{key}", content=data, timeout=30,
                       headers={**self.headers, "content-type": "application/octet-stream", "x-upsert": "true"})
        self._check(r, "upload")

    def get(self, key: str) -> bytes:
        r = httpx.get(f"{self.base}/object/{self.bucket}/{key}", headers=self.headers, timeout=30)
        self._check(r, "download")
        return r.content

    def delete(self, keys: list[str]) -> None:
        if not keys:
            return
        r = httpx.request("DELETE", f"{self.base}/object/{self.bucket}", json={"prefixes": keys},
                          headers=self.headers, timeout=30)
        self._check(r, "delete")


@lru_cache(maxsize=1)
def get_storage():
    if config.STORAGE_BACKEND == "supabase":
        return SupabaseStorage(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY, config.SUPABASE_BUCKET)
    return LocalStorage(config.UPLOAD_DIR)
