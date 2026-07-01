"""Unit tests for the envelope-encryption primitives (pure, no DB)."""

from __future__ import annotations

import pytest

from orchestrator.infra import crypto


def test_secret_round_trip():
    dek = crypto.generate_dek()
    ct = crypto.encrypt_secret("sk-ant-api03-secret", dek)
    assert ct != b"sk-ant-api03-secret"
    assert crypto.decrypt_secret(ct, dek) == "sk-ant-api03-secret"


def test_dek_wrap_unwrap():
    kek = crypto.generate_master_key()
    dek = crypto.generate_dek()
    wrapped = crypto.wrap_dek(dek, kek)
    assert wrapped != dek
    assert crypto.unwrap_dek(wrapped, kek) == dek


def test_wrong_kek_cannot_unwrap():
    dek = crypto.generate_dek()
    wrapped = crypto.wrap_dek(dek, crypto.generate_master_key())
    with pytest.raises(Exception):
        crypto.unwrap_dek(wrapped, crypto.generate_master_key())


def test_ciphertext_does_not_contain_plaintext():
    dek = crypto.generate_dek()
    ct = crypto.encrypt_secret("supersecretkey", dek)
    assert b"supersecretkey" not in ct
