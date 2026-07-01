"""EnvVarSecretStore — reads secrets from process environment (dev/bootstrap only).

Ignores ``org_id`` (single-tenant) and cannot persist. Useful for local
development and for bootstrapping before the encrypted store is configured.

    TODO(port): not for multi-tenant production use — every org would share the
    same env secret. Use FernetSecretStore (or a KMS store) in real deployments.
"""

from __future__ import annotations

import os

from orchestrator.secrets.base import SecretStore

# Maps a logical secret name to the env var that holds it.
_ENV_VAR_FOR = {
    "anthropic": "ANTHROPIC_API_KEY",
}


class EnvVarSecretStore(SecretStore):
    def put(self, org_id: str, name: str, plaintext: str) -> None:
        raise NotImplementedError("EnvVarSecretStore is read-only")

    def get(self, org_id: str, name: str) -> str | None:
        return os.environ.get(_ENV_VAR_FOR.get(name, name)) or None

    def delete(self, org_id: str, name: str) -> None:
        raise NotImplementedError("EnvVarSecretStore is read-only")
