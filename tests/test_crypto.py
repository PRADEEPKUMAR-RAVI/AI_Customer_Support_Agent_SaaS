"""AES-GCM connector-credential encryption: roundtrip + AAD binding (CI gate for [IMP-SEC-8])."""

from __future__ import annotations

import pytest

from app.core.security import decrypt_credential, encrypt_credential, hash_password, verify_password


def test_roundtrip():
    ct = encrypt_credential("s3cret-db-password", tenant_id="t1", connector_id="c1")
    assert decrypt_credential(ct, tenant_id="t1", connector_id="c1") == "s3cret-db-password"


def test_ciphertext_is_bound_to_tenant_and_connector():
    ct = encrypt_credential("hunter2", tenant_id="t1", connector_id="c1")
    # Wrong tenant or connector -> AAD mismatch -> decryption fails (InvalidTag).
    with pytest.raises(Exception):
        decrypt_credential(ct, tenant_id="t2", connector_id="c1")
    with pytest.raises(Exception):
        decrypt_credential(ct, tenant_id="t1", connector_id="c2")


def test_nonce_is_random_per_encryption():
    a = encrypt_credential("same", tenant_id="t1", connector_id="c1")
    b = encrypt_credential("same", tenant_id="t1", connector_id="c1")
    assert a != b  # random 96-bit nonce -> different ciphertext each time


def test_password_hashing():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong", h) is False
