"""Security primitives: password hashing, JWT, opaque token minting, and app-layer AES-GCM
for connector credentials. Owned by Person-1; every module calls these — no hand-rolled crypto.
"""

from __future__ import annotations

import base64
import secrets
import time
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_ph = PasswordHasher()


# --- passwords -----------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# --- JWT -----------------------------------------------------------------------------------
def create_token(claims: dict[str, Any], ttl_seconds: int) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {**claims, "iat": now, "exp": now + ttl_seconds}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Raises ``jwt.PyJWTError`` (incl. ``ExpiredSignatureError``) on any problem."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# --- opaque identifiers --------------------------------------------------------------------
def mint_session_id() -> str:
    """Server-minted opaque 128-bit anonymous session id ([IMP-SEC-3]); never client-supplied."""
    return secrets.token_urlsafe(16)


def mint_widget_key() -> str:
    return "wk_" + secrets.token_urlsafe(24)


# --- connector credential encryption (AES-GCM, AAD-bound) ----------------------------------
def _master_key() -> bytes:
    key = base64.b64decode(get_settings().credential_master_key_b64)
    if len(key) not in (16, 24, 32):
        raise ValueError("CREDENTIAL_MASTER_KEY_B64 must decode to 16/24/32 bytes")
    return key


def encrypt_credential(plaintext: str, *, tenant_id: str, connector_id: str) -> str:
    """AES-GCM with a random 96-bit nonce; ciphertext is bound to (tenant_id, connector_id)
    via AAD so it can't be replayed against another tenant/connector ([IMP-SEC-8])."""
    aad = f"{tenant_id}:{connector_id}".encode()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_master_key()).encrypt(nonce, plaintext.encode(), aad)
    return base64.b64encode(nonce + ct).decode()


def decrypt_credential(token: str, *, tenant_id: str, connector_id: str) -> str:
    aad = f"{tenant_id}:{connector_id}".encode()
    raw = base64.b64decode(token)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(_master_key()).decrypt(nonce, ct, aad).decode()
