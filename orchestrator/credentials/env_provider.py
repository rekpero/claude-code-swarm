"""EnvCredentialProvider — single-tenant / OSS self-host credential source.

Reads the agent credential straight from the process environment. No database,
no encryption, no orgs — this is the path the OSS self-host and your internal
team run, and it preserves the original behaviour exactly:

  * If ``CLAUDE_CODE_OAUTH_TOKEN`` is set, it is injected just as before, so an
    existing single-tenant deployment keeps working byte-for-byte.
  * If ``ANTHROPIC_API_KEY`` is set, it is injected too (BYO Console key also
    works for self-hosters who prefer API billing).

A self-hoster running their own instance on their own Claude credentials for
their own use is ordinary, permitted usage — the third-party reselling
restriction does not apply to them.
"""

from __future__ import annotations

from orchestrator.credentials.base import (
    AgentCredentials,
    CredentialProvider,
    MissingCredentialError,
)
from orchestrator.settings import Settings, get_settings


class EnvCredentialProvider(CredentialProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def for_org(self, org_id: str) -> AgentCredentials:
        # org_id is ignored in single-tenant mode (there is one implicit tenant).
        env: dict[str, str] = {}
        if self._settings.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self._settings.anthropic_api_key
        if self._settings.claude_code_oauth_token:
            # Preserve the original self-host behaviour exactly.
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self._settings.claude_code_oauth_token
        if not env:
            raise MissingCredentialError(org_id, "anthropic")
        return AgentCredentials(env=env)

    def validate(self, org_id: str) -> bool:
        return bool(
            self._settings.anthropic_api_key or self._settings.claude_code_oauth_token
        )
