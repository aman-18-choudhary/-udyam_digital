"""Encryption at rest for KYC data. The key comes from KYC_ENC_KEY or is generated once into a
git-ignored file next to the database, so a copy of the DB or upload folder is useless on its own."""
from __future__ import annotations

import json
import os
from functools import lru_cache

from cryptography.fernet import Fernet

from .config import BASE_DIR


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.getenv("KYC_ENC_KEY")
    if not key:
        keyfile = BASE_DIR / ".kyc.key"
        if not keyfile.exists():
            keyfile.write_bytes(Fernet.generate_key())
            keyfile.chmod(0o600)
        key = keyfile.read_text().strip()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_bytes(b: bytes) -> bytes:
    return _fernet().encrypt(b)


def decrypt_bytes(b: bytes) -> bytes:
    return _fernet().decrypt(b)


def encrypt_json(obj) -> str:
    return _fernet().encrypt(json.dumps(obj).encode()).decode()


def decrypt_json(token: str):
    return json.loads(_fernet().decrypt(token.encode()).decode())
