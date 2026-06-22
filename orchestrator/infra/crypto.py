"""Envelope-encryption primitives (pure, no I/O).

Two-tier key hierarchy so a database dump never exposes usable secrets:

    KEK (master key-encryption-key)  ── wraps ──▶  per-tenant DEK
    DEK (data-encryption-key)        ── encrypts ─▶  the secret (e.g. API key)

Each tenant gets its own DEK, so there is no single key whose compromise dumps
every customer's secret, and no code path that can bulk-decrypt across tenants.
The KEK currently comes from settings; the DEKs are stored wrapped in the
``tenant_keys`` table.

    TODO(kms): move the KEK into AWS KMS / Vault and wrap/unwrap DEKs via the
    KMS API (envelope encryption as a service). This module's function
    signatures stay the same; only the KEK source changes.

All functions here are pure and side-effect free, which keeps them trivially
unit-testable. Persistence of wrapped DEKs and ciphertext lives in the
repository + SecretStore layers.
"""

from __future__ import annotations

from cryptography.fernet import Fernet

# Current key version. Bump when rotating the KEK or changing the scheme so old
# ciphertext can still be identified and migrated.
KEY_VERSION = 1


def generate_master_key() -> str:
    """Generate a new KEK (base64 urlsafe string). Use once to seed config."""
    return Fernet.generate_key().decode("utf-8")


def generate_dek() -> bytes:
    """Generate a new per-tenant data-encryption key (raw Fernet key bytes)."""
    return Fernet.generate_key()


def wrap_dek(dek: bytes, master_key: str) -> bytes:
    """Encrypt (wrap) a tenant DEK with the master KEK for storage at rest."""
    return Fernet(master_key.encode("utf-8")).encrypt(dek)


def unwrap_dek(wrapped_dek: bytes, master_key: str) -> bytes:
    """Decrypt (unwrap) a stored tenant DEK using the master KEK."""
    return Fernet(master_key.encode("utf-8")).decrypt(wrapped_dek)


def encrypt_secret(plaintext: str, dek: bytes) -> bytes:
    """Encrypt a secret string with a tenant DEK. Returns ciphertext bytes."""
    return Fernet(dek).encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes, dek: bytes) -> str:
    """Decrypt ciphertext with a tenant DEK back into the secret string."""
    return Fernet(dek).decrypt(ciphertext).decode("utf-8")
