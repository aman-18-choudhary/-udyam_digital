"""Clerk authentication: verifies the session JWT the browser sends as `Authorization: Bearer <token>`.

Clerk signs session tokens with RS256. We fetch the public keys from the issuer's JWKS endpoint
(cached), check signature, expiry, issuer and, if configured, the authorized party (`azp`).

Roles come from a custom claim. In the Clerk dashboard open Sessions > Customize session token and add:
    { "metadata": "{{user.public_metadata}}" }
then give staff `{ "role": "sales" | "ops" | "admin" }` in their public metadata. Everyone else is a customer.

When CLERK_ISSUER is not set the API runs in dev mode: every request is a single local admin user.
That mode is for local development and tests only; /api/config reports it so the UI can warn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient

from . import config

log = logging.getLogger("udyam.auth")


@dataclass(frozen=True)
class User:
    id: str
    role: str = "customer"
    dev: bool = False

    @property
    def is_staff(self) -> bool:
        return self.role in config.STAFF_ROLES


DEV_USER = User(id="dev-user", role="admin", dev=True)


@lru_cache(maxsize=1)
def _jwks() -> PyJWKClient:
    return PyJWKClient(f"{config.CLERK_ISSUER}/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def verify_token(token: str) -> User:
    try:
        key = _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["RS256"], issuer=config.CLERK_ISSUER, leeway=10,
            options={"require": ["exp", "iat", "sub"], "verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    except Exception as e:  # bad signature, wrong issuer, unreachable JWKS, malformed token
        log.warning("token rejected: %s", type(e).__name__)
        raise HTTPException(401, "Invalid sign-in token.")
    azp = claims.get("azp")
    if config.CLERK_AUTHORIZED_PARTIES and azp and azp not in config.CLERK_AUTHORIZED_PARTIES:
        raise HTTPException(401, "Token was issued for a different application.")
    meta = claims.get("metadata") or claims.get("public_metadata") or {}
    role = meta.get("role") if isinstance(meta, dict) else None
    return User(id=claims["sub"], role=role if role in {"sales", "ops", "admin"} else "customer")


def current_user(request: Request) -> User:
    if not config.AUTH_REQUIRED:
        return DEV_USER
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Please sign in to continue.")
    return verify_token(header[7:].strip())


def require_staff(user: User = Depends(current_user)) -> User:
    if not user.is_staff:
        raise HTTPException(403, "This area is for Accel staff.")
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(403, f"Requires role: {' or '.join(roles)}.")
        return user
    return dep
