"""SecretStore interface.

A SecretStore persists per-tenant secrets by ``(org_id, name)``. ``name`` is the
logical secret name — for this slice it is the credential provider (e.g.
``"anthropic"``). Implementations decide *how* secrets are stored (encrypted in
the DB, in a cloud KMS/secrets manager, or plain env for dev).

Callers (e.g. CredentialProvider) depend only on this interface, so the storage
backend can change without touching the execution path.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SecretStore(ABC):
    @abstractmethod
    def put(self, org_id: str, name: str, plaintext: str) -> None:
        """Store (or replace) a secret for an org."""

    @abstractmethod
    def get(self, org_id: str, name: str) -> str | None:
        """Return the plaintext secret, or None if absent."""

    @abstractmethod
    def delete(self, org_id: str, name: str) -> None:
        """Remove a secret for an org."""
