"""Credential + tenant-key repositories.

These deal only in ciphertext and wrapped keys — encryption/decryption lives in
the SecretStore. Keeping crypto out of the repository keeps responsibilities
clean (repository = persistence, SecretStore = crypto policy).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from orchestrator.models.credential import (
    PROVIDER_ANTHROPIC,
    OrgCredential,
    TenantKey,
)
from orchestrator.repositories.base import Repository


class TenantKeyRepository(Repository[TenantKey]):
    model = TenantKey

    def get_for_org(self, org_id: str) -> TenantKey | None:
        return self.session.get(TenantKey, org_id)

    def create(self, org_id: str, wrapped_dek: bytes, key_version: int) -> TenantKey:
        return self.add(
            TenantKey(org_id=org_id, wrapped_dek=wrapped_dek, key_version=key_version)
        )


class CredentialRepository(Repository[OrgCredential]):
    model = OrgCredential

    def get(
        self, org_id: str, provider: str = PROVIDER_ANTHROPIC
    ) -> OrgCredential | None:
        stmt = select(OrgCredential).where(
            OrgCredential.org_id == org_id, OrgCredential.provider == provider
        )
        return self.session.scalars(stmt).first()

    def upsert(
        self,
        org_id: str,
        ciphertext: bytes,
        key_version: int,
        provider: str = PROVIDER_ANTHROPIC,
        status: str = "active",
    ) -> OrgCredential:
        """Insert or replace the org's credential for a provider.

        Uses catch-and-retry to handle the race where two concurrent first-time
        ``put()`` calls for the same (org_id, provider) both observe ``get()``
        returning ``None`` and attempt to INSERT simultaneously — the loser
        catches IntegrityError and re-reads the winner's row.
        """
        cred = self.get(org_id, provider)
        if cred is None:
            cred = OrgCredential(
                org_id=org_id,
                provider=provider,
                ciphertext=ciphertext,
                key_version=key_version,
                status=status,
            )
            try:
                # SAVEPOINT around just the INSERT: on IntegrityError only this
                # nested transaction rolls back, leaving the outer transaction
                # (managed by the caller's session_scope) intact.
                with self.session.begin_nested():
                    self.session.add(cred)
                    self.session.flush()
                return cred
            except IntegrityError:
                # Concurrent caller won the race to INSERT — re-read their row.
                cred = self.get(org_id, provider)
                if cred is None:
                    raise
        cred.ciphertext = ciphertext
        cred.key_version = key_version
        cred.status = status
        self.session.flush()
        return cred

    def set_status(
        self,
        org_id: str,
        status: str,
        provider: str = PROVIDER_ANTHROPIC,
        validated: bool = False,
    ) -> None:
        cred = self.get(org_id, provider)
        if cred is None:
            return
        cred.status = status
        if validated:
            cred.last_validated_at = datetime.now(timezone.utc)
        self.session.flush()
