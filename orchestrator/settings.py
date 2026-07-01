"""Typed application settings (v2).

Single source of truth for configuration, replacing scattered ``os.environ.get``
calls. Built on pydantic-settings so values are validated and typed at startup.

This module is introduced as part of the v2 BYO-key refactor and coexists with
the legacy ``orchestrator/config.py`` during the strangler-fig migration. New
code should depend on ``get_settings()``; legacy modules continue to import
``config`` until they are ported.

    TODO(port): migrate remaining ``config.py`` consumers onto ``Settings`` and
    delete ``config.py`` once nothing imports it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed runtime configuration.

    Values are read from environment variables (and a local ``.env`` file in
    development). Names match the existing env vars so this is drop-in.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # legacy/unknown env vars are tolerated
        case_sensitive=False,
    )

    # === Deployment mode ===
    # "single_tenant" (default, OSS self-host — runs exactly like before: env
    #   credentials, no Postgres, no encryption setup) or "multi_tenant" (managed
    #   cloud — per-org encrypted credentials in Postgres).
    deployment_mode: str = Field(default="single_tenant", alias="DEPLOYMENT_MODE")

    # === Database (multi_tenant only) ===
    # Postgres DSN, e.g. postgresql+psycopg://user:pass@localhost:5432/swarmops
    database_url: str = Field(
        default="postgresql+psycopg://swarmops:swarmops@localhost:5432/swarmops",
        alias="DATABASE_URL",
    )

    @property
    def is_multi_tenant(self) -> bool:
        return self.deployment_mode == "multi_tenant"

    # === Secrets / encryption ===
    # Which SecretStore backend to use: "fernet" (encrypted at rest) or "env" (dev only).
    secret_backend: str = Field(default="fernet", alias="SECRET_BACKEND")
    # The master key-encryption-key (KEK). Base64 urlsafe 32-byte Fernet key.
    # TODO(kms): source this from AWS KMS / Vault instead of an env var before
    # serving real customer keys. The SecretStore interface does not change.
    secrets_master_key: str | None = Field(default=None, alias="SECRETS_MASTER_KEY")

    # === Credentials ===
    # Which CredentialProvider to use for agent runs: "api_key" (BYO Anthropic key).
    credential_provider: str = Field(default="api_key", alias="CREDENTIAL_PROVIDER")
    # Base URL used by ApiKeyCredentialProvider.validate().
    anthropic_base_url: str = Field(
        default="https://api.anthropic.com", alias="ANTHROPIC_BASE_URL"
    )

    # === Single-tenant credentials (env-based, no DB) ===
    # In single_tenant mode the agent runs with whichever of these is set,
    # preserving the original self-host behaviour exactly.
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    claude_code_oauth_token: str = Field(default="", alias="CLAUDE_CODE_OAUTH_TOKEN")
    gh_token: str = Field(default="", alias="GH_TOKEN")

    # === Paths ===
    workspaces_dir: Path = Field(
        default=Path("/root/workspaces"), alias="WORKSPACES_DIR"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
