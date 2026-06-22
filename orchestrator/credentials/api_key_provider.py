"""ApiKeyCredentialProvider — BYO Anthropic Console API key.

Resolves the org's Anthropic API key from the SecretStore and hands it to the
agent as ``ANTHROPIC_API_KEY``. This is the v2 model: each tenant runs on its
own Console key (billed by Anthropic to them), replacing the shared, now-banned
``CLAUDE_CODE_OAUTH_TOKEN``.

    TODO(wif): a sibling WifCredentialProvider can mint short-lived OIDC tokens
    (no stored secret) behind this same interface for enterprise customers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager

import httpx
from sqlalchemy.orm import Session

from orchestrator.credentials.base import (
    AgentCredentials,
    CredentialProvider,
    MissingCredentialError,
)
from orchestrator.models.credential import (
    PROVIDER_ANTHROPIC,
    STATUS_ACTIVE,
    STATUS_INVALID,
)
from orchestrator.repositories.credential_repo import CredentialRepository
from orchestrator.secrets.base import SecretStore

logger = logging.getLogger(__name__)


class ApiKeyCredentialProvider(CredentialProvider):
    def __init__(
        self,
        secret_store: SecretStore,
        session_scope: Callable[[], AbstractContextManager[Session]],
        anthropic_base_url: str = "https://api.anthropic.com",
    ) -> None:
        self._secrets = secret_store
        self._session_scope = session_scope
        self._base_url = anthropic_base_url.rstrip("/")

    def for_org(self, org_id: str) -> AgentCredentials:
        key = self._secrets.get(org_id, PROVIDER_ANTHROPIC)
        if not key:
            raise MissingCredentialError(org_id, PROVIDER_ANTHROPIC)
        # Claude Code CLI honours ANTHROPIC_API_KEY for Console (API) billing.
        # TODO(port): if a future Claude Code release changes this env contract,
        # switch the agent runner to the Claude Agent SDK / Messages API, which
        # is unambiguously API-key native. The interface here does not change.
        return AgentCredentials(env={"ANTHROPIC_API_KEY": key})

    def validate(self, org_id: str) -> bool:
        """Hit a cheap endpoint to confirm the key works; persist the result."""
        key = self._secrets.get(org_id, PROVIDER_ANTHROPIC)
        if not key:
            return False
        ok = self._probe(key)
        with self._session_scope() as s:
            CredentialRepository(s).set_status(
                org_id,
                STATUS_ACTIVE if ok else STATUS_INVALID,
                validated=ok,
            )
        return ok

    def _probe(self, key: str) -> bool:
        try:
            resp = httpx.get(
                f"{self._base_url}/v1/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=10.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Anthropic key validation failed: %s", e)
            return False
