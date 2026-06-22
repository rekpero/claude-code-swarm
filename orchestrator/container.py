"""Composition root — builds and wires the v2 singletons in one place.

Everything that needs a SecretStore or CredentialProvider gets it from here,
rather than importing config globals. This is the only module that knows which
concrete implementations are in use, so swapping a backend (e.g. Fernet → KMS)
is a one-line change confined to this file.

Usage::

    from orchestrator.container import get_container
    creds = get_container().credential_provider.for_org(org_id)
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from orchestrator.credentials.api_key_provider import ApiKeyCredentialProvider
from orchestrator.credentials.base import CredentialProvider
from orchestrator.credentials.env_provider import EnvCredentialProvider
from orchestrator.infra.db import session_scope
from orchestrator.secrets.base import SecretStore
from orchestrator.secrets.env_store import EnvVarSecretStore
from orchestrator.secrets.fernet_store import FernetSecretStore
from orchestrator.settings import Settings, get_settings


@dataclass(frozen=True)
class Container:
    # secret_store is None in single-tenant mode (no encrypted store needed).
    secret_store: SecretStore | None
    credential_provider: CredentialProvider


def _build_secret_store(settings: Settings) -> SecretStore:
    if settings.secret_backend == "env":
        return EnvVarSecretStore()
    # default: encrypted-at-rest
    return FernetSecretStore(
        master_key=settings.secrets_master_key or "",
        session_scope=session_scope,
    )


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()

    # Single-tenant (OSS self-host / internal team): env-based credentials, no
    # Postgres, no encryption. Runs exactly like the original deployment.
    if not settings.is_multi_tenant:
        return Container(
            secret_store=None,
            credential_provider=EnvCredentialProvider(settings),
        )

    # Multi-tenant (managed cloud): per-org encrypted credentials in Postgres.
    secret_store = _build_secret_store(settings)
    if settings.credential_provider == "api_key":
        credential_provider: CredentialProvider = ApiKeyCredentialProvider(
            secret_store=secret_store,
            session_scope=session_scope,
            anthropic_base_url=settings.anthropic_base_url,
        )
    # TODO(wif): elif settings.credential_provider == "wif": WifCredentialProvider(...)
    else:
        raise ValueError(f"Unknown CREDENTIAL_PROVIDER: {settings.credential_provider}")

    return Container(
        secret_store=secret_store,
        credential_provider=credential_provider,
    )


@lru_cache(maxsize=1)
def get_container() -> Container:
    """Return the process-wide container singleton."""
    return build_container()
