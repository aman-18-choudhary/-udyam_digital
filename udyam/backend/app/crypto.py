"""Encryption at rest for KYC data. The key comes from KYC_ENC_KEY or is generated once into a
git-ignored file next to the database, so a copy of the DB or upload folder is useless on its own."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from cryptography.fernet import Fernet

from .config import BASE_DIR


def clean_key(raw: str) -> str:
    """Forgive the usual paste mistakes: whitespace, surrounding quotes, and the 'KYC_ENC_KEY=' prefix."""
    k = (raw or "").strip()
    if k.upper().startswith("KYC_ENC_KEY"):
        k = k.split("=", 1)[1].strip() if "=" in k else ""
    if len(k) >= 2 and k[0] == k[-1] and k[0] in "\"'":
        k = k[1:-1].strip()
    return k


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = clean_key(os.getenv("KYC_ENC_KEY") or "")
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


def key_hints(raw: str) -> list[str]:
    """What looks wrong with the configured key, described without revealing any of its characters."""
    hints, k = [], clean_key(raw)
    if raw != raw.strip():
        hints.append("had leading or trailing whitespace (trimmed)")
    if not k:
        return hints + ["is empty after cleaning"]
    if len(k) != 44:
        hints.append(f"length is {len(k)}, a Fernet key is exactly 44")
    if not re.fullmatch(r"[A-Za-z0-9_\-]*=?", k):
        hints.append("contains characters that are not URL-safe base64 (only letters, digits, - and _ allowed)")
    if not k.endswith("="):
        hints.append("does not end with '=' (copy was probably cut short)")
    return hints


def selfcheck() -> str:
    """'ok' or a description of the problem. Never contains the key."""
    try:
        return "ok" if decrypt_json(encrypt_json({"t": 1})) == {"t": 1} else "roundtrip mismatch"
    except Exception as e:
        raw = os.getenv("KYC_ENC_KEY") or ""
        return (f"invalid KYC_ENC_KEY ({type(e).__name__}): " + ("; ".join(key_hints(raw)) or "unknown problem")
                + ". Generate one with: python -c \"from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())\"")
