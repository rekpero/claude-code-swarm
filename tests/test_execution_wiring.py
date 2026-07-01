"""Tests that the execution path resolves per-org credentials (not a shared token)."""

from __future__ import annotations

from orchestrator.agent_pool import AgentPool
from orchestrator.credentials.base import AgentCredentials, CredentialProvider
from orchestrator.infra.db import session_scope
from orchestrator.repositories.organization_repo import (
    DEFAULT_ORG_SLUG,
    OrganizationRepository,
)


class FakeProvider(CredentialProvider):
    def __init__(self) -> None:
        self.seen_org_ids: list[str] = []

    def for_org(self, org_id):
        self.seen_org_ids.append(org_id)
        return AgentCredentials(env={"ANTHROPIC_API_KEY": "sk-ant-api03-INJECTED"})

    def validate(self, org_id):
        return True


def test_agent_credential_env_injects_per_org_key(multi_tenant, db):
    provider = FakeProvider()
    pool = AgentPool(credential_provider=provider)

    env = pool._agent_credential_env(workspace_id=None)

    assert env == {"ANTHROPIC_API_KEY": "sk-ant-api03-INJECTED"}
    # multi-tenant resolves against a real org id (the bootstrap default)
    assert provider.seen_org_ids
    with session_scope() as s:
        default = OrganizationRepository(s).get_by_slug(DEFAULT_ORG_SLUG)
        assert default is not None
        assert provider.seen_org_ids[0] == default.id


def test_no_oauth_token_in_multi_tenant_credential_env(multi_tenant, db):
    pool = AgentPool(credential_provider=FakeProvider())
    env = pool._agent_credential_env(workspace_id=None)
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
