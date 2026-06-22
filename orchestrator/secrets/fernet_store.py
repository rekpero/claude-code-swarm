"""FernetSecretStore — envelope-encrypted secret storage in Postgres.

Storage layout (see models/credential.py):
  * ``tenant_keys``     — one wrapped DEK per org
  * ``org_credentials`` — ciphertext of each provider secret, keyed (org, provider)

Crypto policy lives here; the raw crypto math is in ``infra/crypto.py`` and the
persistence is in the credential repositories. A DB dump yields only ciphertext
and wrapped DEKs — useless without the master KEK held outside the database.

    TODO(kms): a sibling KmsSecretStore can implement this same interface using a
    cloud KMS/secrets manager. Swapping it is a one-line change in container.py.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from orchestrator.infra import crypto
from orchestrator.repositories.credential_repo import (
    CredentialRepository,
    TenantKeyRepository,
)
from orchestrator.secrets.base import SecretStore


class FernetSecretStore(SecretStore):
    def __init__(
        self,
        master_key: str,
        session_scope: Callable[[], AbstractContextManager[Session]],
    ) -> None:
        if not master_key:
            raise ValueError(
                "FernetSecretStore requires SECRETS_MASTER_KEY. "
                "Generate one with orchestrator.infra.crypto.generate_master_key()."
            )
        self._master_key = master_key
        self._session_scope = session_scope

    # --- internal: get or lazily create the org's data-encryption-key ---
    def _get_dek(self, tk_repo: TenantKeyRepository, org_id: str) -> bytes | None:
        tk = tk_repo.get_for_org(org_id)
        if tk is None:
            return None
        return crypto.unwrap_dek(tk.wrapped_dek, self._master_key)

    def _get_or_create_dek(self, tk_repo: TenantKeyRepository, org_id: str) -> bytes:
        tk = tk_repo.get_for_org(org_id)
        if tk is not None:
            return crypto.unwrap_dek(tk.wrapped_dek, self._master_key)
        dek = crypto.generate_dek()
        wrapped = crypto.wrap_dek(dek, self._master_key)
        tk_repo.create(org_id, wrapped, crypto.KEY_VERSION)
        return dek

    def put(self, org_id: str, name: str, plaintext: str) -> None:
        with self._session_scope() as s:
            dek = self._get_or_create_dek(TenantKeyRepository(s), org_id)
            ciphertext = crypto.encrypt_secret(plaintext, dek)
            CredentialRepository(s).upsert(
                org_id, ciphertext, crypto.KEY_VERSION, provider=name
            )

    def get(self, org_id: str, name: str) -> str | None:
        with self._session_scope() as s:
            dek = self._get_dek(TenantKeyRepository(s), org_id)
            if dek is None:
                return None
            cred = CredentialRepository(s).get(org_id, provider=name)
            if cred is None:
                return None
            return crypto.decrypt_secret(cred.ciphertext, dek)

    def delete(self, org_id: str, name: str) -> None:
        with self._session_scope() as s:
            cred = CredentialRepository(s).get(org_id, provider=name)
            if cred is not None:
                s.delete(cred)
